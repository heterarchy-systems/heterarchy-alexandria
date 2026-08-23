"""Real PyO3 document-analysis parity against the frozen pre-cutover corpus."""

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
CORPUS_PATH = REPOSITORY_ROOT / "native/corpora/document_analysis/v1/cases.json"
MODULE_NAME = "heterarchy_alexandria_native"

sys.path.insert(0, str(BACKEND_ROOT))



type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Narrow dynamic extension surface used by this parity gate."""

    def compute_contract_version(self) -> int: ...

    def analyze_document_batch_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    corpus = _load_json_object(CORPUS_PATH)
    cases = _require_list(corpus, "cases")
    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-native-") as directory:
        module = _load_native_module(Path(directory))
        if module.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        request = {
            "contract_version": 1,
            "documents": [
                {
                    "document_id": _require_string(case, "case_id"),
                    "relative_path": _require_string(case, "relative_path"),
                    "text": _require_string(case, "text"),
                }
                for case in map(_require_object, cases)
            ],
        }
        raw_response = module.analyze_document_batch_json(
            json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
        )
        response = _load_json_bytes(raw_response)
        _compare_native_to_corpus(cases, response)
    print(f"ffi-parity: PASS cases={len(cases)} call_count=1")
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
    names = (
        "libheterarchy_alexandria_native.dylib",
        "libheterarchy_alexandria_native.so",
        "heterarchy_alexandria_native.dll",
    )
    for name in names:
        candidate = target / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"native extension artifact is missing under {target}")




def _compare_native_to_corpus(cases: list[JsonValue], response: dict[str, JsonValue]) -> None:
    if response.get("contract_version") != 1 or response.get("analysis_version") != 1:
        raise AssertionError("native response versions are invalid")
    outcomes = _require_list(response, "results")
    if len(outcomes) != len(cases):
        raise AssertionError("native batch result cardinality changed")
    for case_value, outcome_value in zip(cases, outcomes, strict=True):
        case = _require_object(case_value)
        outcome = _require_object(outcome_value)
        expected = _require_object(case["expected"])
        case_id = _require_string(case, "case_id")
        relative_path = _require_string(case, "relative_path")
        if outcome.get("document_id") != case_id:
            raise AssertionError(f"{case_id}: native result identity mismatch")
        if outcome.get("relative_path") != relative_path:
            raise AssertionError(f"{case_id}: native result path mismatch")
        if outcome.get("status") != expected.get("status"):
            raise AssertionError(f"{case_id}: native result status mismatch")
        if outcome.get("status") == "error":
            _compare_native_error(case_id, expected, outcome)
            continue
        analysis = _require_object(outcome["analysis"])
        if analysis.get("body") != expected.get("body"):
            raise AssertionError(f"{case_id}: native body mismatch")
        if _native_frontmatter(analysis) != _expected_frontmatter(expected):
            raise AssertionError(f"{case_id}: native frontmatter mismatch")
        _validate_source_ranges(case_id, _require_string(case, "text"), analysis)


def _compare_native_error(
    case_id: str,
    expected: Mapping[str, JsonValue],
    outcome: Mapping[str, JsonValue],
) -> None:
    expected_error = _require_object(expected["error"])
    actual_error = _require_object(outcome["error"])
    if actual_error != expected_error:
        raise AssertionError(f"{case_id}: native structured error mismatch")


def _expected_frontmatter(expected: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    entries = _require_list(expected, "frontmatter")
    result: dict[str, JsonValue] = {}
    for entry_value in entries:
        entry = _require_object(entry_value)
        result[_require_string(entry, "key")] = _decode_tagged(_require_object(entry["value"]))
    return result


def _native_frontmatter(analysis: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    entries = _require_list(analysis, "frontmatter")
    result: dict[str, JsonValue] = {}
    for entry_value in entries:
        entry = _require_object(entry_value)
        key = _require_string(entry, "key")
        if key in result:
            raise AssertionError(f"native output repeated frontmatter key {key}")
        result[key] = _decode_tagged(_require_object(entry["value"]))
    return result


def _decode_tagged(tagged: Mapping[str, JsonValue]) -> JsonValue:
    kind = _require_string(tagged, "kind")
    if kind == "null":
        return None
    value = tagged.get("value")
    if kind == "string":
        if not isinstance(value, str):
            raise TypeError("tagged string value is invalid")
        return value
    if kind == "integer":
        if not isinstance(value, str):
            raise TypeError("tagged integer value is invalid")
        return int(value)
    if kind == "float":
        if not isinstance(value, str):
            raise TypeError("tagged float value is invalid")
        return float(value)
    if kind == "boolean":
        if not isinstance(value, bool):
            raise TypeError("tagged boolean value is invalid")
        return value
    if kind == "sequence":
        if not isinstance(value, list):
            raise TypeError("tagged sequence value is invalid")
        return [_decode_tagged(_require_object(item)) for item in value]
    raise ValueError(f"unsupported tagged frontmatter kind: {kind}")


def _validate_source_ranges(
    case_id: str,
    text: str,
    analysis: Mapping[str, JsonValue],
) -> None:
    byte_length = len(text.encode())
    body_range = _require_object(analysis["body_source_range"])
    body_start = _require_int(body_range, "start")
    body_end = _require_int(body_range, "end")
    if not 0 <= body_start <= body_end <= byte_length:
        raise AssertionError(f"{case_id}: invalid native body source range")
    headings = _require_list(analysis, "headings")
    previous_start = -1
    for heading_value in headings:
        heading = _require_object(heading_value)
        source_range = _require_object(heading["source_range"])
        start = _require_int(source_range, "start")
        end = _require_int(source_range, "end")
        if not body_start <= start <= end <= byte_length or start < previous_start:
            raise AssertionError(f"{case_id}: invalid or unstable heading source range")
        previous_start = start


def _load_json_object(path: Path) -> dict[str, JsonValue]:
    value = json.loads(path.read_text())
    return _require_object(value)


def _load_json_bytes(payload: bytes) -> dict[str, JsonValue]:
    value = json.loads(payload)
    return _require_object(value)


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
