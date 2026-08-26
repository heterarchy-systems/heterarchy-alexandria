"""Real PyO3 raw data-integrity parity against the frozen Python corpus."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sysconfig
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPOSITORY_ROOT / "native/golden/raw_data_integrity_cases.json"
MODULE_NAME = "heterarchy_alexandria_native"


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Narrow dynamic extension surface used by this parity gate."""

    def compute_contract_version(self) -> int: ...

    def scan_raw_data_integrity_batch_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    """Run one coarse native call across every frozen raw-integrity case."""
    corpus = _load_json_object(CORPUS_PATH)
    cases = _require_list(corpus, "cases")
    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-native-") as directory:
        module = _load_native_module(Path(directory))
        if module.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        request: dict[str, JsonValue] = {
            "contract_version": 1,
            "raw_integrity_version": 1,
            "collection_fields": _require_list(corpus, "collection_fields"),
            "boolean_fields": _require_list(corpus, "boolean_fields"),
            "unrecoverable_redacted_url_pattern": _require_string(
                corpus,
                "unrecoverable_redacted_url_pattern",
            ),
            "documents": [
                {
                    "relative_path": f"cases/{_require_string(case, 'name')}.md",
                    "text": _require_string(case, "markdown"),
                }
                for case in map(_require_object, cases)
            ],
        }
        raw_response = module.scan_raw_data_integrity_batch_json(
            json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
        )
        response = _load_json_bytes(raw_response)
        _compare_native_to_corpus(cases, response)
    print(f"raw-integrity-ffi-parity: PASS cases={len(cases)} call_count=1")
    return 0


def _compare_native_to_corpus(
    cases: list[JsonValue],
    response: dict[str, JsonValue],
) -> None:
    """Compare native warnings to the frozen Python scanner output."""
    if response.get("contract_version") != 1:
        raise AssertionError("native raw-integrity contract version changed")
    if response.get("raw_integrity_version") != 1:
        raise AssertionError("native raw-integrity schema version changed")
    results = _require_list(response, "results")
    if len(results) != len(cases):
        raise AssertionError("native raw-integrity batch cardinality changed")
    for case_value, result_value in zip(cases, results, strict=True):
        case = _require_object(case_value)
        result = _require_object(result_value)
        name = _require_string(case, "name")
        if result.get("relative_path") != f"cases/{name}.md":
            raise AssertionError(f"{name}: native result path mismatch")
        actual = _aggregate_findings(_require_list(result, "findings"))
        expected = _normalized_expected(_require_list(case, "expected"))
        if actual != expected:
            raise AssertionError(
                f"{name}: native raw-integrity findings mismatch: {actual!r} != {expected!r}"
            )


def _aggregate_findings(findings: list[JsonValue]) -> list[dict[str, JsonValue]]:
    counts: dict[str, int] = defaultdict(int)
    fields: dict[str, set[str]] = defaultdict(set)
    for finding_value in findings:
        finding = _require_object(finding_value)
        code = _require_string(finding, "code")
        counts[code] += 1
        field_name = finding.get("field_name")
        if isinstance(field_name, str):
            fields[code].add(field_name)
        elif field_name is not None:
            raise TypeError("native field_name must be string or null")
    order = (
        "LEGACY_TUPLE_COLLECTION",
        "EMPTY_COLLECTION_SCALAR",
        "INVALID_COLLECTION_TYPE",
        "STRING_BOOLEAN",
        "INVALID_BOOLEAN_VALUE",
        "UNRECOVERABLE_REDACTED_URL",
    )
    return [
        {
            "code": code,
            "count": counts[code],
            "fields": sorted(fields[code]),
        }
        for code in order
        if counts[code]
    ]


def _normalized_expected(values: list[JsonValue]) -> list[dict[str, JsonValue]]:
    expected: list[dict[str, JsonValue]] = []
    for value in values:
        item = _require_object(value)
        expected.append(
            {
                "code": _require_string(item, "code"),
                "count": _require_int(item, "count"),
                "fields": _require_string_list(item, "fields"),
            }
        )
    return expected


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
    if Path(str(module.__file__)).resolve() != destination.resolve():
        raise RuntimeError("native provenance mismatch")
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
    return _require_object(json.loads(path.read_text(encoding="utf-8")))


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


def _require_string_list(
    container: Mapping[str, JsonValue],
    key: str,
) -> list[str]:
    values = _require_list(container, key)
    if not all(isinstance(item, str) for item in values):
        raise TypeError(f"expected JSON string list at {key}")
    return cast(list[str], values)


if __name__ == "__main__":
    raise SystemExit(main())
