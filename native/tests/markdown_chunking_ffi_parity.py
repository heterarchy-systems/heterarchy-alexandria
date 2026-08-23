"""Real PyO3 Markdown chunking parity against the frozen pre-cutover corpus."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import sysconfig
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
CORPUS_PATH = REPOSITORY_ROOT / "native/corpora/chunking/v1/cases.json"
MODULE_NAME = "heterarchy_alexandria_native"

sys.path.insert(0, str(BACKEND_ROOT))



type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Narrow dynamic extension surface used by this parity gate."""

    def compute_contract_version(self) -> int: ...

    def chunk_markdown_batch_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    corpus = _load_json_object(CORPUS_PATH)
    cases = [_require_object(value) for value in _require_list(corpus, "cases")]
    calls = 0
    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-native-") as directory:
        module = _load_native_module(Path(directory))
        if module.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        grouped = _group_by_policy(cases)
        for (max_chars, overlap_chars), policy_cases in grouped.items():
            request = {
                "contract_version": 1,
                "chunking_version": 1,
                "max_chars": max_chars,
                "overlap_chars": overlap_chars,
                "documents": [
                    {
                        "document_id": _require_string(case, "case_id"),
                        "relative_path": _require_string(case, "relative_path"),
                        "title": _require_string(case, "title"),
                        "content": _require_string(case, "content"),
                    }
                    for case in policy_cases
                ],
            }
            raw_response = module.chunk_markdown_batch_json(
                json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
            )
            response = _load_json_bytes(raw_response)
            _compare_native_policy_batch(
                policy_cases,
                response,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            )
            calls += 1
    print(f"chunk-ffi-parity: PASS cases={len(cases)} call_count={calls}")
    return 0


def _group_by_policy(
    cases: list[dict[str, JsonValue]],
) -> dict[tuple[int, int], list[dict[str, JsonValue]]]:
    grouped: dict[tuple[int, int], list[dict[str, JsonValue]]] = defaultdict(list)
    for case in cases:
        grouped[
            (
                _require_int(case, "max_chars"),
                _require_int(case, "overlap_chars"),
            )
        ].append(case)
    return dict(grouped)


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




def _compare_native_policy_batch(
    cases: list[dict[str, JsonValue]],
    response: dict[str, JsonValue],
    *,
    max_chars: int,
    overlap_chars: int,
) -> None:
    if response.get("contract_version") != 1 or response.get("chunking_version") != 1:
        raise AssertionError("native chunk response versions are invalid")
    policy = _require_object(response["policy"])
    if policy != {"max_chars": max_chars, "overlap_chars": overlap_chars}:
        raise AssertionError("native chunk response policy mismatch")
    outcomes = _require_list(response, "results")
    if len(outcomes) != len(cases):
        raise AssertionError("native chunk result cardinality changed")
    for case, outcome_value in zip(cases, outcomes, strict=True):
        outcome = _require_object(outcome_value)
        case_id = _require_string(case, "case_id")
        if outcome.get("status") != "success":
            raise AssertionError(f"{case_id}: native chunking unexpectedly failed")
        if outcome.get("document_id") != case_id:
            raise AssertionError(f"{case_id}: native chunk identity mismatch")
        if outcome.get("relative_path") != _require_string(case, "relative_path"):
            raise AssertionError(f"{case_id}: native chunk path mismatch")
        native_chunks = _require_list(outcome, "chunks")
        expected_chunks = _require_list(case, "expected")
        if len(native_chunks) != len(expected_chunks):
            raise AssertionError(f"{case_id}: native chunk count mismatch")
        for expected_value, native_value in zip(
            expected_chunks, native_chunks, strict=True
        ):
            expected = _require_object(expected_value)
            native = _require_object(native_value)
            for key in ("chunk_index", "heading", "content"):
                if native.get(key) != expected.get(key):
                    raise AssertionError(f"{case_id}: native chunk {key} mismatch")
            _validate_native_metadata(case, native)


def _validate_native_metadata(
    case: Mapping[str, JsonValue],
    chunk: Mapping[str, JsonValue],
) -> None:
    case_id = _require_string(case, "case_id")
    content = _require_string(case, "content")
    title = _require_string(case, "title")
    source_kind = _require_string(chunk, "source_kind")
    expected_source_kind = "content" if content.strip() else "title_fallback"
    if source_kind != expected_source_kind:
        raise AssertionError(f"{case_id}: native source kind mismatch")
    source = content if source_kind == "content" else title
    source_range = _require_object(chunk["source_range"])
    char_start = _require_int(source_range, "char_start")
    char_end = _require_int(source_range, "char_end")
    byte_start = _require_int(source_range, "byte_start")
    byte_end = _require_int(source_range, "byte_end")
    chunk_content = _require_string(chunk, "content")
    if source[char_start:char_end] != chunk_content:
        raise AssertionError(f"{case_id}: native character source range mismatch")
    if source.encode()[byte_start:byte_end].decode() != chunk_content:
        raise AssertionError(f"{case_id}: native byte source range mismatch")
    heading = chunk.get("heading")
    heading_path = _require_list(chunk, "heading_path")
    if heading_path and heading_path[-1] != heading:
        raise AssertionError(f"{case_id}: native heading hierarchy leaf mismatch")


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
