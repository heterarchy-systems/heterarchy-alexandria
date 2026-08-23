"""Measure Rust-authoritative retrieval-kernel core and real-extension FFI overhead."""

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
from types import ModuleType
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

MODULE_NAME = "heterarchy_alexandria_native"
SCALES = (50, 1_000, 10_000, 50_000)
RESULT_LIMIT = 50


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Real extension function measured by this performance harness."""

    def compute_retrieval_kernel_json(self, payload: bytes) -> bytes: ...


class CandidateBundle:
    """Prebuilt JSON candidate representations for one performance scale."""

    def __init__(
        self,
        fts_specs: list[dict[str, JsonValue]],
        vector_specs: list[dict[str, JsonValue]],
    ) -> None:
        self.fts_specs = fts_specs
        self.vector_specs = vector_specs


def main() -> int:
    report_path = _required_environment_path(
        "HETERARCHY_ALEXANDRIA_RETRIEVAL_PERF_REPORT"
    )
    core_report_path = _required_environment_path(
        "HETERARCHY_ALEXANDRIA_RETRIEVAL_CORE_PERF_REPORT"
    )
    core_report = _load_json_object(core_report_path)
    with tempfile.TemporaryDirectory(
        prefix="heterarchy-alexandria-native-"
    ) as directory:
        native = _load_native_module(Path(directory))
        scenarios = [_measure_scenario(native, scale) for scale in SCALES]

    report: dict[str, JsonValue] = {
        "schema_version": 1,
        "feature": "retrieval_kernel",
        "scope": "candidate_compute_and_real_json_ffi_only",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "peak_rss_bytes": _peak_rss_bytes(),
        },
        "result_limit": RESULT_LIMIT,
        "direct_core": core_report,
        "scenarios": scenarios,
        "quality_evidence": {
            "frozen_pre_cutover_compatibility_corpus": (
                "native/corpora/retrieval_kernel/v1/cases.json"
            ),
            "real_ffi_compatibility_gate": "run_by_cargo_xtask_test",
            "exact_title_corpus": (
                "backend/benchmarks/golden_cases.exact_title.v1.json"
            ),
            "semantic_corpus": "backend/benchmarks/golden_cases.semantic.v1.json",
            "benchmark_tool_gate": "run_separately_by_xtask_perf",
            "live_endpoint_recall_metrics": "not_run",
            "reason": (
                "This performance harness intentionally does not import or reimplement the "
                "retired Python ranking engine; correctness is owned by the frozen corpus and "
                "real-extension compatibility gates."
            ),
        },
        "interpretation": [
            "Native FFI timing includes strict JSON decode, Rust ranking, and JSON encode.",
            "Direct-core timing excludes Python and JSON conversion overhead.",
            "The retired Python ranking implementation is not a benchmark oracle after cutover.",
            "PostgreSQL FTS/pgvector query latency and graph enrichment are intentionally excluded.",
            "Live endpoint provenance and quality remain a separate cutover/performance gate.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"retrieval-kernel-perf: CANDIDATE_PASS scenarios={len(scenarios)} "
        f"report={report_path} live_quality=NOT_RUN"
    )
    return 0


def _measure_scenario(native: NativeModule, candidates_per_lane: int) -> JsonValue:
    bundle = _candidate_bundle(candidates_per_lane)
    fusion_request = {
        "operation": "merge_hybrid",
        "limit": RESULT_LIMIT,
        "fts_candidates": bundle.fts_specs,
        "vector_candidates": bundle.vector_specs,
    }
    best_request = {
        "operation": "rank_best",
        "limit": RESULT_LIMIT,
        "candidates": bundle.fts_specs,
    }
    fusion_payload = _kernel_payload(fusion_request)
    best_payload = _kernel_payload(best_request)

    native_fused = _native_result(native, fusion_payload)
    native_best = _native_result(native, best_payload)
    fusion_result_count = _bounded_result_count(
        native_fused,
        operation="merge_hybrid",
        candidates_per_lane=candidates_per_lane,
    )
    best_result_count = _bounded_result_count(
        native_best,
        operation="rank_best",
        candidates_per_lane=candidates_per_lane,
    )

    iterations = _iteration_count(candidates_per_lane)
    sample_count = _sample_count(candidates_per_lane)
    native_fusion_ns = _median_elapsed_ns(
        lambda: len(native.compute_retrieval_kernel_json(fusion_payload)),
        iterations,
        sample_count,
    )
    native_best_ns = _median_elapsed_ns(
        lambda: len(native.compute_retrieval_kernel_json(best_payload)),
        iterations,
        sample_count,
    )
    total_candidate_count = candidates_per_lane * 2
    return {
        "candidates_per_lane": candidates_per_lane,
        "total_candidate_count": total_candidate_count,
        "iterations": iterations,
        "sample_count": sample_count,
        "native_ffi_fusion_median_milliseconds": _ns_to_ms(native_fusion_ns),
        "native_ffi_best_match_median_milliseconds": _ns_to_ms(native_best_ns),
        "fusion_result_count": fusion_result_count,
        "best_match_result_count": best_result_count,
        "native_fusion_request_bytes": len(fusion_payload),
        "native_best_match_request_bytes": len(best_payload),
        "native_fusion_response_bytes": len(
            native.compute_retrieval_kernel_json(fusion_payload)
        ),
        "native_best_match_response_bytes": len(
            native.compute_retrieval_kernel_json(best_payload)
        ),
    }


def _candidate_bundle(count: int) -> CandidateBundle:
    fts_specs = [_fts_spec(index, count) for index in range(count)]
    vector_specs = [_vector_spec(index, count) for index in range(count)]
    return CandidateBundle(fts_specs, vector_specs)


def _fts_spec(index: int, count: int) -> dict[str, JsonValue]:
    context_index = _duplicate_adjusted_index(index, 17)
    score = _descending_score(index, count)
    return {
        "context_id": f"context-{context_index}",
        "score": score,
        "fts_score": score,
        "vector_score": None,
        "why_retrieved": "lexical candidate",
    }


def _vector_spec(index: int, count: int) -> dict[str, JsonValue]:
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


def _kernel_payload(request: dict[str, JsonValue]) -> bytes:
    return _encode(
        {
            "contract_version": 1,
            "retrieval_version": 1,
            "request": request,
        }
    )


def _native_result(native: NativeModule, payload: bytes) -> JsonValue:
    response = _load_json_bytes(native.compute_retrieval_kernel_json(payload))
    return response["result"]


def _bounded_result_count(
    value: JsonValue,
    operation: str,
    candidates_per_lane: int,
) -> int:
    if not isinstance(value, list):
        raise TypeError(f"{operation}: expected list result at scale {candidates_per_lane}")
    if len(value) > RESULT_LIMIT:
        raise AssertionError(
            f"{operation}: result limit exceeded at scale {candidates_per_lane}"
        )
    return len(value)


def _median_elapsed_ns(
    operation: Callable[[], int],
    iterations: int,
    sample_count: int,
) -> float:
    _consume_integer(operation())
    samples: list[int] = []
    for _ in range(sample_count):
        started = time.perf_counter_ns()
        accumulator = 0
        for _ in range(iterations):
            accumulator ^= operation()
        elapsed = time.perf_counter_ns() - started
        _consume_integer(accumulator)
        samples.append(elapsed // iterations)
    return float(statistics.median(samples))


def _iteration_count(candidates_per_lane: int) -> int:
    if candidates_per_lane <= 50:
        return 200
    if candidates_per_lane <= 1_000:
        return 20
    if candidates_per_lane <= 10_000:
        return 2
    return 1


def _sample_count(candidates_per_lane: int) -> int:
    if candidates_per_lane <= 1_000:
        return 5
    if candidates_per_lane <= 10_000:
        return 3
    return 1


def _duplicate_adjusted_index(index: int, cadence: int) -> int:
    return index - 1 if index > 0 and index % cadence == 0 else index


def _descending_score(index: int, count: int) -> float:
    denominator = 1 << count.bit_length()
    return (count - index) / denominator


def _consume_integer(value: int) -> None:
    if value < 0:
        raise AssertionError("unreachable negative benchmark accumulator")


def _ns_to_ms(value: float) -> float:
    return round(value / 1_000_000.0, 6)


def _peak_rss_bytes() -> int:
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(maximum if sys.platform == "darwin" else maximum * 1_024)


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
    target = REPOSITORY_ROOT / "native/target/release"
    for name in (
        "libheterarchy_alexandria_native.dylib",
        "libheterarchy_alexandria_native.so",
        "heterarchy_alexandria_native.dll",
    ):
        candidate = target / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"release native extension artifact is missing under {target}"
    )


def _required_environment_path(name: str) -> Path:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(
            f"required performance report environment is missing: {name}"
        )
    return Path(value).resolve()


def _encode(value: Mapping[str, JsonValue]) -> bytes:
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


if __name__ == "__main__":
    raise SystemExit(main())
