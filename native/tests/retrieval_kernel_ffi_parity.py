"""Real PyO3 retrieval-kernel parity against the frozen pre-cutover corpus."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sysconfig
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPOSITORY_ROOT / "native/corpora/retrieval_kernel/v1/cases.json"
MODULE_NAME = "heterarchy_alexandria_native"


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Narrow dynamic extension surface used by this parity gate."""

    def compute_contract_version(self) -> int: ...

    def compute_retrieval_kernel_json(self, payload: bytes) -> bytes: ...

    def retrieval_merge_hybrid_indices(
        self,
        fts_context_ids: list[str],
        vector_context_ids: list[str],
        limit: int,
    ) -> list[tuple[str, int, int | None, int | None, float]]: ...


def main() -> int:
    corpus = _load_json_object(CORPUS_PATH)
    if corpus.get("schema_version") != 1:
        raise AssertionError("retrieval kernel corpus schema version must be 1")
    if corpus.get("feature") != "retrieval_kernel":
        raise AssertionError("retrieval kernel corpus feature identity drifted")

    call_count = 0
    with tempfile.TemporaryDirectory(
        prefix="heterarchy-alexandria-native-"
    ) as directory:
        native = _load_native_module(Path(directory))
        if native.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")

        for raw_case in _require_list(corpus, "candidate_limit_cases"):
            case = _require_object(raw_case)
            result = _compute(
                native,
                {
                    "operation": "hybrid_candidate_limit",
                    "limit": _require_int(case, "limit"),
                },
            )
            call_count += 1
            _assert_response(result, "hybrid_candidate_limit", case["expected"])

        for raw_case in _require_list(corpus, "fusion_cases"):
            case = _require_object(raw_case)
            result = _compute(
                native,
                {
                    "operation": "merge_hybrid",
                    "limit": _require_int(case, "limit"),
                    "fts_candidates": _require_list(case, "fts_matches"),
                    "vector_candidates": _require_list(case, "vector_matches"),
                },
            )
            call_count += 1
            _assert_response(result, "merge_hybrid", case["expected"])
            compact = native.retrieval_merge_hybrid_indices(
                _context_ids(_require_list(case, "fts_matches")),
                _context_ids(_require_list(case, "vector_matches")),
                _require_int(case, "limit"),
            )
            call_count += 1
            _assert_compact_fusion(
                compact,
                expected=_require_list(case, "expected"),
                fts_matches=_require_list(case, "fts_matches"),
                vector_matches=_require_list(case, "vector_matches"),
            )

        for raw_case in _require_list(corpus, "best_match_cases"):
            case = _require_object(raw_case)
            result = _compute(
                native,
                {
                    "operation": "rank_best",
                    "limit": _require_int(case, "limit"),
                    "candidates": _require_list(case, "matches"),
                },
            )
            call_count += 1
            _assert_response(result, "rank_best", case["expected"])

        for raw_case in _require_list(corpus, "cosine_cases"):
            case = _require_object(raw_case)
            result = _compute(
                native,
                {
                    "operation": "cosine_similarity",
                    "left": _require_list(case, "left"),
                    "right": _require_list(case, "right"),
                },
            )
            call_count += 1
            _assert_response(result, "cosine_similarity", case["expected"])

    print(
        "retrieval-kernel-ffi-parity: PASS "
        f"candidate_limit={len(_require_list(corpus, 'candidate_limit_cases'))} "
        f"fusion={len(_require_list(corpus, 'fusion_cases'))} "
        f"compact_fusion={len(_require_list(corpus, 'fusion_cases'))} "
        f"best={len(_require_list(corpus, 'best_match_cases'))} "
        f"cosine={len(_require_list(corpus, 'cosine_cases'))} "
        f"call_count={call_count}"
    )
    return 0


def _compute(
    native: NativeModule,
    request: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "contract_version": 1,
        "retrieval_version": 1,
        "request": request,
    }
    return _load_json_bytes(native.compute_retrieval_kernel_json(_encode(payload)))


def _assert_response(
    response: dict[str, JsonValue],
    operation: str,
    expected: JsonValue,
) -> None:
    if response.get("contract_version") != 1:
        raise AssertionError(f"{operation}: unexpected contract version")
    if response.get("retrieval_version") != 1:
        raise AssertionError(f"{operation}: unexpected retrieval version")
    if response.get("operation") != operation:
        raise AssertionError(f"{operation}: operation identity drift")
    if response.get("result") != expected:
        raise AssertionError(f"{operation}: real-extension result mismatch")


def _context_ids(matches: list[JsonValue]) -> list[str]:
    return [_require_string(_require_object(match), "context_id") for match in matches]


def _assert_compact_fusion(
    actual: list[tuple[str, int, int | None, int | None, float]],
    *,
    expected: list[JsonValue],
    fts_matches: list[JsonValue],
    vector_matches: list[JsonValue],
) -> None:
    fts_first = _first_unique_indexes(fts_matches)
    vector_first = _first_unique_indexes(vector_matches)
    expected_rows: list[tuple[str, int, int | None, int | None, float]] = []
    for raw in expected:
        item = _require_object(raw)
        context_id = _require_string(item, "context_id")
        representative = _require_object(item.get("representative"))
        lane = _require_string(representative, "lane")
        lane_index = _require_int(representative, "lane_index")
        score_value = item.get("score")
        if not isinstance(score_value, (int, float)) or isinstance(score_value, bool):
            raise TypeError("expected numeric fusion score")
        expected_rows.append(
            (
                lane,
                lane_index,
                fts_first.get(context_id),
                vector_first.get(context_id),
                float(score_value),
            )
        )
    if actual != expected_rows:
        raise AssertionError(
            f"compact merge_hybrid real-extension mismatch: {actual!r} != {expected_rows!r}"
        )


def _first_unique_indexes(matches: list[JsonValue]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for index, raw in enumerate(matches):
        context_id = _require_string(_require_object(raw), "context_id")
        indexes.setdefault(context_id, index)
    return indexes


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


def _require_int(value: dict[str, JsonValue], key: str) -> int:
    candidate = value.get(key)
    if not isinstance(candidate, int) or isinstance(candidate, bool):
        raise TypeError(f"expected JSON integer at {key}")
    return candidate


def _require_string(value: dict[str, JsonValue], key: str) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str):
        raise TypeError(f"expected JSON string at {key}")
    return candidate


if __name__ == "__main__":
    raise SystemExit(main())
