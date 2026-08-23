"""Real PyO3 hash/fingerprint/change parity against the frozen pre-cutover corpus."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import sysconfig
import tempfile
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
CORPUS_PATH = REPOSITORY_ROOT / "native/corpora/fingerprint/v1/cases.json"
MODULE_NAME = "heterarchy_alexandria_native"

sys.path.insert(0, str(BACKEND_ROOT))



type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Narrow dynamic extension surface used by this parity gate."""

    def compute_contract_version(self) -> int: ...

    def compute_hash_batch_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    corpus = _load_json_object(CORPUS_PATH)
    cases = [_require_object(value) for value in _require_list(corpus, "cases")]
    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-native-") as directory:
        module = _load_native_module(Path(directory))
        if module.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        request = {
            "contract_version": 1,
            "hashing_version": 1,
            "documents": [
                {
                    "document_id": _require_string(case, "document_id"),
                    "relative_path": _require_string(case, "relative_path"),
                    "text": _require_string(case, "text"),
                    "embedding_fingerprint": case.get("embedding_fingerprint"),
                    "indexed_at": case.get("indexed_at"),
                    "previous": case["previous"],
                    "current_chunk_identities": case.get(
                        "current_chunk_identities"
                    ),
                    "current_edge_identities": case.get("current_edge_identities"),
                }
                for case in cases
            ],
        }
        raw_response = module.compute_hash_batch_json(
            json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
        )
        response = _load_json_bytes(raw_response)
        _compare_native_to_corpus(cases, response)
    total_bytes = sum(len(_require_string(case, "text").encode()) for case in cases)
    print(
        f"hash-ffi-parity: PASS cases={len(cases)} bytes={total_bytes} call_count=1"
    )
    return 0


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












def _compare_native_to_corpus(
    cases: list[dict[str, JsonValue]],
    response: dict[str, JsonValue],
) -> None:
    if response.get("contract_version") != 1 or response.get("hashing_version") != 1:
        raise AssertionError("native hash response versions are invalid")
    results = _require_list(response, "results")
    if len(results) != len(cases):
        raise AssertionError("native hash result cardinality changed")
    for case, result_value in zip(cases, results, strict=True):
        result = _require_object(result_value)
        case_id = _require_string(case, "case_id")
        if result.get("document_id") != _require_string(case, "document_id"):
            raise AssertionError(f"{case_id}: native hash identity mismatch")
        if result.get("relative_path") != _require_string(case, "relative_path"):
            raise AssertionError(f"{case_id}: native hash path mismatch")
        expected = _require_object(case["expected"])
        for key in ("content_hash", "embedding_fingerprint", "change_report"):
            if result.get(key) != expected.get(key):
                raise AssertionError(f"{case_id}: native {key} mismatch")
        digest = _require_string(result, "content_hash")
        if len(digest) != 64 or digest.lower() != digest:
            raise AssertionError(f"{case_id}: native digest encoding is invalid")


def _optional_string(
    container: Mapping[str, JsonValue],
    key: str,
) -> str | None:
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"expected optional JSON string at {key}")
    return value


def _optional_string_list(value: JsonValue) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("expected optional JSON string list")
    return cast(list[str], value)


def _load_json_object(path: Path) -> dict[str, JsonValue]:
    return _require_object(json.loads(path.read_text()))


def _load_json_bytes(payload: bytes) -> dict[str, JsonValue]:
    return _require_object(json.loads(payload))


def _require_object(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("expected a JSON object with string keys")
    return value


def _require_list(container: Mapping[str, JsonValue], key: str) -> list[JsonValue]:
    value = container.get(key)
    if not isinstance(value, list):
        raise TypeError(f"expected JSON list at {key}")
    return value


def _require_string(container: Mapping[str, JsonValue], key: str) -> str:
    value = container.get(key)
    if not isinstance(value, str):
        raise TypeError(f"expected JSON string at {key}")
    return value


def _require_int(container: Mapping[str, JsonValue], key: str) -> int:
    value = container.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"expected JSON integer at {key}")
    return value


def _require_bool(container: Mapping[str, JsonValue], key: str) -> bool:
    value = container.get(key)
    if not isinstance(value, bool):
        raise TypeError(f"expected JSON boolean at {key}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
