"""Real PyO3 reference and edge extraction parity against the frozen pre-cutover corpus."""

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
CORPUS_PATH = REPOSITORY_ROOT / "native/corpora/link_extraction/v1/cases.json"
MODULE_NAME = "heterarchy_alexandria_native"

sys.path.insert(0, str(BACKEND_ROOT))



type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Narrow dynamic extension surface used by this parity gate."""

    def compute_contract_version(self) -> int: ...

    def extract_reference_batch_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    corpus = _load_json_object(CORPUS_PATH)
    cases = [_require_object(value) for value in _require_list(corpus, "cases")]
    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-native-") as directory:
        module = _load_native_module(Path(directory))
        if module.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        request = {
            "contract_version": 1,
            "extraction_version": 1,
            "documents": [
                {
                    "note_id": _require_string(case, "note_id"),
                    "relative_path": _require_string(case, "relative_path"),
                    "alexandria_root": _require_string(case, "alexandria_root"),
                    "body": _require_string(case, "body"),
                    "frontmatter_edges": _require_list(case, "frontmatter_edges"),
                }
                for case in cases
            ],
        }
        raw_response = module.extract_reference_batch_json(
            json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
        )
        response = _load_json_bytes(raw_response)
        _compare_native_to_corpus(cases, response)
    reference_count = sum(
        len(_require_list(_require_object(value), "expected_body_targets"))
        for value in cases
    )
    edge_count = sum(
        len(_require_list(_require_object(value), "expected_edges")) for value in cases
    )
    print(
        f"reference-ffi-parity: PASS cases={len(cases)} "
        f"accepted_targets={reference_count} edges={edge_count} call_count=1"
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
    if response.get("contract_version") != 1 or response.get("extraction_version") != 1:
        raise AssertionError("native reference response versions are invalid")
    results = _require_list(response, "results")
    if len(results) != len(cases):
        raise AssertionError("native reference result cardinality changed")
    for case, result_value in zip(cases, results, strict=True):
        result = _require_object(result_value)
        case_id = _require_string(case, "case_id")
        if result.get("note_id") != _require_string(case, "note_id"):
            raise AssertionError(f"{case_id}: native note identity mismatch")
        if result.get("relative_path") != _require_string(case, "relative_path"):
            raise AssertionError(f"{case_id}: native source path mismatch")
        references = [_require_object(value) for value in _require_list(result, "references")]
        accepted_targets = [
            reference["normalized_target_path"]
            for reference in references
            if reference.get("normalized_target_path") is not None
        ]
        if accepted_targets != _require_list(case, "expected_body_targets"):
            raise AssertionError(f"{case_id}: native normalized target order mismatch")
        _validate_reference_ranges(case, references)
        native_edges = [_require_object(value) for value in _require_list(result, "edges")]
        expected_edges = [
            _require_object(value) for value in _require_list(case, "expected_edges")
        ]
        if len(native_edges) != len(expected_edges):
            raise AssertionError(f"{case_id}: native edge count mismatch")
        for expected, actual in zip(expected_edges, native_edges, strict=True):
            _compare_native_edge(case_id, expected, actual)


def _compare_native_edge(
    case_id: str,
    expected: Mapping[str, JsonValue],
    actual: Mapping[str, JsonValue],
) -> None:
    for key in (
        "edge_id",
        "source_note_id",
        "source_path",
        "target_note_id",
        "target_path",
        "relation",
        "confidence",
        "source_kind",
        "identity_material",
    ):
        if actual.get(key) != expected.get(key):
            raise AssertionError(f"{case_id}: native edge {key} mismatch")
    reference_index = actual.get("reference_index")
    if actual.get("source_kind") == "frontmatter" and reference_index is not None:
        raise AssertionError(f"{case_id}: frontmatter edge has a body reference index")
    if actual.get("source_kind") == "wikilink" and not isinstance(reference_index, int):
        raise AssertionError(f"{case_id}: wikilink edge lacks a reference index")


def _validate_reference_ranges(
    case: Mapping[str, JsonValue],
    references: list[dict[str, JsonValue]],
) -> None:
    case_id = _require_string(case, "case_id")
    body = _require_string(case, "body")
    previous_start = -1
    for expected_index, reference in enumerate(references):
        if reference.get("reference_index") != expected_index:
            raise AssertionError(f"{case_id}: unstable native reference sequence")
        source_range = _require_object(reference["source_range"])
        char_start = _require_int(source_range, "char_start")
        char_end = _require_int(source_range, "char_end")
        byte_start = _require_int(source_range, "byte_start")
        byte_end = _require_int(source_range, "byte_end")
        raw_syntax = _require_string(reference, "raw_syntax")
        if byte_start < previous_start:
            raise AssertionError(f"{case_id}: unstable native reference source order")
        if body[char_start:char_end] != raw_syntax:
            raise AssertionError(f"{case_id}: native reference character range mismatch")
        if body.encode()[byte_start:byte_end].decode() != raw_syntax:
            raise AssertionError(f"{case_id}: native reference byte range mismatch")
        previous_start = byte_start


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
