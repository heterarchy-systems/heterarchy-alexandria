"""Real PyO3 bulk embedding preparation/finalization parity."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import sysconfig
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
CORPUS_PATH = REPOSITORY_ROOT / "native/corpora/bulk_embedding/v1/cases.json"
MODULE_NAME = "heterarchy_alexandria_native"

sys.path.insert(0, str(BACKEND_ROOT))


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Narrow dynamic extension surface used by this parity gate."""

    def compute_contract_version(self) -> int: ...

    def prepare_bulk_embedding_batch_json(self, payload: bytes) -> bytes: ...

    def finalize_bulk_embedding_batch_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    corpus = _load_json_object(CORPUS_PATH)
    cases = [_require_object(value) for value in _require_list(corpus, "cases")]
    call_count = 0
    finalized_count = 0
    with tempfile.TemporaryDirectory(
        prefix="heterarchy-alexandria-native-"
    ) as directory:
        module = _load_native_module(Path(directory))
        if module.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        for case in cases:
            request = _request_from_case(case)
            preparation_payload: dict[str, JsonValue] = {
                "contract_version": 1,
                "embedding_version": 1,
                "request": request,
            }
            preparation = _load_json_bytes(
                module.prepare_bulk_embedding_batch_json(_encode(preparation_payload))
            )
            call_count += 1
            if preparation != _require_object(case["expected_preparation"]):
                raise AssertionError(
                    f"{_require_string(case, 'case_id')}: preparation FFI mismatch"
                )
            inference_batches = case.get("inference_batches")
            if inference_batches is None:
                continue
            finalization_payload: dict[str, JsonValue] = {
                **preparation_payload,
                "inference_batches": inference_batches,
            }
            result = _load_json_bytes(
                module.finalize_bulk_embedding_batch_json(_encode(finalization_payload))
            )
            call_count += 1
            finalized_count += 1
            if result != _require_object(case["expected_result"]):
                raise AssertionError(
                    f"{_require_string(case, 'case_id')}: finalization FFI mismatch"
                )
    item_count = sum(len(_require_list(case, "documents")) for case in cases)
    print(
        f"bulk-embedding-ffi-parity: PASS cases={len(cases)} "
        f"items={item_count} finalized={finalized_count} call_count={call_count}"
    )
    return 0


def _request_from_case(case: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "model": case["model"],
        "batch_size": _require_int(case, "batch_size"),
        "documents": _require_list(case, "documents"),
    }


def _load_native_module(temp_root: Path) -> NativeModule:
    library = _native_library_path()
    suffix_value = sysconfig.get_config_var("EXT_SUFFIX")
    if not isinstance(suffix_value, str) or not suffix_value:
        raise RuntimeError("Python EXT_SUFFIX is unavailable")
    destination = temp_root / f"{MODULE_NAME}{suffix_value}"
    shutil.copy2(library, destination)
    specification = importlib.util.spec_from_file_location(MODULE_NAME, destination)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load native extension from {destination}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    if not isinstance(module, ModuleType):
        raise RuntimeError("native extension loader returned an invalid module")
    loaded_path = Path(str(module.__file__)).resolve()
    if loaded_path != destination.resolve():
        raise RuntimeError(f"native provenance mismatch: loaded {loaded_path}")
    return cast(NativeModule, module)


def _native_library_path() -> Path:
    configured = os.environ.get("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY")
    if configured:
        path = Path(configured).resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"configured native library does not exist: {path}")
    target = REPOSITORY_ROOT / "native/target/debug"
    for name in (
        "libheterarchy_alexandria_native.dylib",
        "libheterarchy_alexandria_native.so",
        "heterarchy_alexandria_native.dll",
    ):
        candidate = target / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"native extension artifact is missing under {target}")


def _encode(value: dict[str, JsonValue]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _load_json_object(path: Path) -> dict[str, JsonValue]:
    return _require_object(
        cast(JsonValue, json.loads(path.read_text(encoding="utf-8")))
    )


def _load_json_bytes(value: bytes) -> dict[str, JsonValue]:
    return _require_object(cast(JsonValue, json.loads(value)))


def _require_object(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise TypeError("expected JSON object")
    return value


def _require_list(value: dict[str, JsonValue], key: str) -> list[JsonValue]:
    candidate = value.get(key)
    if not isinstance(candidate, list):
        raise TypeError(f"expected JSON list at {key}")
    return candidate


def _require_string(value: dict[str, JsonValue], key: str) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str):
        raise TypeError(f"expected JSON string at {key}")
    return candidate


def _require_int(value: dict[str, JsonValue], key: str) -> int:
    candidate = value.get(key)
    if not isinstance(candidate, int) or isinstance(candidate, bool):
        raise TypeError(f"expected JSON integer at {key}")
    return candidate


if __name__ == "__main__":
    raise SystemExit(main())
