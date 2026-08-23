"""Real PyO3 graph projection and algorithm parity against the frozen corpus."""

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
CORPUS_PATH = REPOSITORY_ROOT / "native/corpora/graph_compute/v1/cases.json"
MODULE_NAME = "heterarchy_alexandria_native"

sys.path.insert(0, str(BACKEND_ROOT))


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Narrow dynamic extension surface used by this parity gate."""

    def compute_contract_version(self) -> int: ...

    def compute_graph_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    corpus = _load_json_object(CORPUS_PATH)
    cases = [_require_object(value) for value in _require_list(corpus, "cases")]
    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-native-") as directory:
        module = _load_native_module(Path(directory))
        if module.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        for case in cases:
            request = {
                "contract_version": 1,
                "graph_compute_version": 1,
                "batch_size": _require_int(case, "batch_size"),
                "source_notes": _require_list(case, "source_notes"),
                "source_edges": _require_list(case, "source_edges"),
                "previous_projection": case.get("previous_projection"),
                "traversal_requests": _require_list(case, "traversal_requests"),
                "lineage_requests": _require_list(case, "lineage_requests"),
            }
            raw_response = module.compute_graph_json(
                json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
            )
            response = _load_json_bytes(raw_response)
            _compare_native_case(case, response)
    node_count = sum(
        len(
            _require_list(
                _require_object(_require_object(case["expected"])["projection"]),
                "nodes",
            )
        )
        for case in cases
    )
    edge_count = sum(
        len(
            _require_list(
                _require_object(_require_object(case["expected"])["projection"]),
                "edges",
            )
        )
        for case in cases
    )
    print(
        f"graph-ffi-parity: PASS cases={len(cases)} "
        f"nodes={node_count} edges={edge_count} call_count={len(cases)}"
    )
    return 0


def _compare_native_case(
    case: Mapping[str, JsonValue],
    response: Mapping[str, JsonValue],
) -> None:
    case_id = _require_string(case, "case_id")
    if response.get("contract_version") != 1:
        raise AssertionError(f"{case_id}: native contract version mismatch")
    if response.get("graph_compute_version") != 1:
        raise AssertionError(f"{case_id}: native graph compute version mismatch")
    expected = _require_object(case["expected"])
    for field in (
        "projection",
        "batches",
        "issues",
        "metrics",
        "structural_diagnostics",
        "analysis",
    ):
        if response.get(field) != expected.get(field):
            raise AssertionError(f"{case_id}: native graph field {field} mismatch")


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


if __name__ == "__main__":
    raise SystemExit(main())
