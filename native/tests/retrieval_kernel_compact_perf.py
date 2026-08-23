"""Measure the Rust-authoritative compact retrieval boundary and DTO materialization."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import resource
import shutil
import statistics
import sys
import sysconfig
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.memory.domain.entities.context_read_models import (  # noqa: E402
    ContextChunkRecord,
    ContextRecord,
    ContextSearchMatch,
)

MODULE_NAME = "heterarchy_alexandria_native"
SCALES = (50, 1_000, 10_000, 50_000)
RESULT_LIMIT = 50
FUSED_REASON = (
    "Context ranked across lexical and semantic vector evidence "
    "using best-lane reciprocal-rank fusion."
)


class NativeModule(Protocol):
    def retrieval_merge_hybrid_indices(
        self,
        fts_context_ids: list[str],
        vector_context_ids: list[str],
        limit: int,
    ) -> list[tuple[str, int, int | None, int | None, float]]: ...

    def retrieval_rank_best_indices(
        self, candidates: list[tuple[str, float]], limit: int
    ) -> list[tuple[int, float]]: ...


class CandidateBundle:
    def __init__(
        self,
        fts_specs: list[dict[str, object]],
        vector_specs: list[dict[str, object]],
        fts_matches: list[ContextSearchMatch],
        vector_matches: list[ContextSearchMatch],
    ) -> None:
        self.fts_specs = fts_specs
        self.vector_specs = vector_specs
        self.fts_matches = fts_matches
        self.vector_matches = vector_matches


def main() -> int:
    report_path = _required_environment_path(
        "HETERARCHY_ALEXANDRIA_RETRIEVAL_COMPACT_PERF_REPORT"
    )
    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-native-") as directory:
        native = _load_native_module(Path(directory))
        scenarios = [_measure_scenario(native, scale) for scale in SCALES]

    report = {
        "schema_version": 1,
        "feature": "retrieval_kernel",
        "scope": "compact_tuple_index_ffi_with_python_materialization",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "peak_rss_bytes": _peak_rss_bytes(),
        },
        "result_limit": RESULT_LIMIT,
        "scenarios": scenarios,
        "quality_evidence": {
            "frozen_pre_cutover_compatibility_corpus": (
                "native/corpora/retrieval_kernel/v1/cases.json"
            ),
            "real_ffi_compatibility_gate": "run_by_cargo_xtask_test",
        },
        "interpretation": [
            "Native compact timings include Python extraction of IDs/scores, PyO3 conversion, Rust ranking, and reconstruction of existing ContextSearchMatch DTOs.",
            "Heavyweight Context/Chunk objects never cross the native boundary.",
            "The compact functions reuse the same Rust ranking algorithm used by the strict JSON compatibility adapter.",
            "The retired Python ranking implementation is not retained as a performance or correctness oracle after cutover.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"retrieval-kernel-compact-perf: PASS scenarios={len(scenarios)} report={report_path}")
    return 0


def _measure_scenario(native: NativeModule, candidates_per_lane: int) -> dict[str, object]:
    bundle = _candidate_bundle(candidates_per_lane)
    compact_fused = _compact_merge(native, bundle.fts_matches, bundle.vector_matches, RESULT_LIMIT)
    compact_best = _compact_best(native, bundle.fts_matches, RESULT_LIMIT)
    _validate_bounded_matches(
        compact_fused,
        operation="compact_merge_hybrid",
        candidates_per_lane=candidates_per_lane,
    )
    _validate_bounded_matches(
        compact_best,
        operation="compact_rank_best",
        candidates_per_lane=candidates_per_lane,
    )

    iterations = _iteration_count(candidates_per_lane)
    sample_count = _sample_count(candidates_per_lane)
    compact_fusion_ns = _median_elapsed_ns(
        lambda: len(_compact_merge(native, bundle.fts_matches, bundle.vector_matches, RESULT_LIMIT)),
        iterations,
        sample_count,
    )
    compact_best_ns = _median_elapsed_ns(
        lambda: len(_compact_best(native, bundle.fts_matches, RESULT_LIMIT)),
        iterations,
        sample_count,
    )
    return {
        "candidates_per_lane": candidates_per_lane,
        "compact_ffi_fusion_median_milliseconds": _ns_to_ms(compact_fusion_ns),
        "compact_ffi_best_match_median_milliseconds": _ns_to_ms(compact_best_ns),
        "fusion_result_count": len(compact_fused),
        "best_match_result_count": len(compact_best),
    }


def _compact_merge(
    native: NativeModule,
    fts_matches: list[ContextSearchMatch],
    vector_matches: list[ContextSearchMatch],
    limit: int,
) -> list[ContextSearchMatch]:
    results = native.retrieval_merge_hybrid_indices(
        [match.context.id for match in fts_matches],
        [match.context.id for match in vector_matches],
        limit,
    )
    materialized: list[ContextSearchMatch] = []
    for lane, representative_index, fts_index, vector_index, score in results:
        representative = (
            fts_matches[representative_index]
            if lane == "fts"
            else vector_matches[representative_index]
        )
        fts_score = None if fts_index is None else fts_matches[fts_index].fts_score
        vector_score = (
            None if vector_index is None else vector_matches[vector_index].vector_score
        )
        why_retrieved = (
            FUSED_REASON
            if fts_score is not None and vector_score is not None
            else representative.why_retrieved
        )
        materialized.append(
            ContextSearchMatch(
                context=representative.context,
                chunk=representative.chunk,
                score=score,
                fts_score=fts_score,
                vector_score=vector_score,
                why_retrieved=why_retrieved,
            )
        )
    return materialized


def _compact_best(
    native: NativeModule,
    matches: list[ContextSearchMatch],
    limit: int,
) -> list[ContextSearchMatch]:
    results = native.retrieval_rank_best_indices(
        [(match.context.id, match.score) for match in matches], limit
    )
    return [matches[index] for index, _score in results]


def _candidate_bundle(count: int) -> CandidateBundle:
    fts_specs = [_fts_spec(index, count) for index in range(count)]
    vector_specs = [_vector_spec(index, count) for index in range(count)]
    return CandidateBundle(
        fts_specs,
        vector_specs,
        [_match(spec, lane="fts", lane_index=index) for index, spec in enumerate(fts_specs)],
        [_match(spec, lane="vector", lane_index=index) for index, spec in enumerate(vector_specs)],
    )


def _fts_spec(index: int, count: int) -> dict[str, object]:
    context_index = _duplicate_adjusted_index(index, 17)
    score = _descending_score(index, count)
    return {
        "context_id": f"context-{context_index}",
        "score": score,
        "fts_score": score,
        "vector_score": None,
        "why_retrieved": "lexical candidate",
    }


def _vector_spec(index: int, count: int) -> dict[str, object]:
    context_id = (
        f"vector-only-{index}"
        if index % 5 == 0
        else f"context-{_duplicate_adjusted_index(index, 19)}"
    )
    score = _descending_score(index, count)
    return {
        "context_id": context_id,
        "score": score,
        "fts_score": None,
        "vector_score": score,
        "why_retrieved": "semantic vector candidate",
    }


def _match(spec: Mapping[str, object], *, lane: str, lane_index: int) -> ContextSearchMatch:
    context_id = cast(str, spec["context_id"])
    context = cast(ContextRecord, SimpleNamespace(id=context_id, marker=f"{lane}:{lane_index}"))
    chunk = cast(ContextChunkRecord, SimpleNamespace(id=f"chunk-{lane}:{lane_index}"))
    return ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=float(cast(float, spec["score"])),
        fts_score=cast(float | None, spec["fts_score"]),
        vector_score=cast(float | None, spec["vector_score"]),
        why_retrieved=cast(str, spec["why_retrieved"]),
    )


def _validate_bounded_matches(
    matches: list[ContextSearchMatch],
    operation: str,
    candidates_per_lane: int,
) -> None:
    if len(matches) > RESULT_LIMIT:
        raise AssertionError(
            f"{operation}: result limit exceeded at scale {candidates_per_lane}"
        )


def _median_elapsed_ns(operation: Callable[[], int], iterations: int, sample_count: int) -> float:
    operation()
    samples: list[int] = []
    for _ in range(sample_count):
        started = time.perf_counter_ns()
        accumulator = 0
        for _ in range(iterations):
            accumulator ^= operation()
        elapsed = time.perf_counter_ns() - started
        if accumulator < 0:
            raise AssertionError("unreachable benchmark accumulator")
        samples.append(elapsed // iterations)
    return float(statistics.median(samples))


def _iteration_count(count: int) -> int:
    if count <= 50:
        return 200
    if count <= 1_000:
        return 20
    if count <= 10_000:
        return 2
    return 1


def _sample_count(count: int) -> int:
    if count <= 1_000:
        return 5
    if count <= 10_000:
        return 3
    return 1


def _duplicate_adjusted_index(index: int, cadence: int) -> int:
    return index - 1 if index > 0 and index % cadence == 0 else index


def _descending_score(index: int, count: int) -> float:
    denominator = 1 << count.bit_length()
    return (count - index) / denominator


def _ns_to_ms(value: float) -> float:
    return round(value / 1_000_000.0, 6)


def _peak_rss_bytes() -> int:
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(maximum if sys.platform == "darwin" else maximum * 1_024)


def _load_native_module(temp_root: Path) -> NativeModule:
    library = _native_library_path()
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not isinstance(suffix, str) or not suffix:
        raise RuntimeError("Python EXT_SUFFIX is unavailable")
    destination = temp_root / f"{MODULE_NAME}{suffix}"
    shutil.copy2(library, destination)
    specification = importlib.util.spec_from_file_location(MODULE_NAME, destination)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load native extension from {destination}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    if not isinstance(module, ModuleType):
        raise RuntimeError("native extension loader returned an invalid module")
    return cast(NativeModule, module)


def _native_library_path() -> Path:
    configured = os.environ.get("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY")
    if not configured:
        raise RuntimeError("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY is required")
    path = Path(configured).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _required_environment_path(name: str) -> Path:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"required environment is missing: {name}")
    return Path(value).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
