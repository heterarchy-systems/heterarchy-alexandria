"""Typed contracts shared by Context RAG benchmark components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BenchmarkQuery:
    """One benchmark query with accepted Context ids or Obsidian titles."""

    query: str
    project: str | None = None
    expected_context_ids: tuple[str, ...] = ()
    expected_titles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Validated command-line configuration for one benchmark run."""

    base_url: str
    queries: tuple[BenchmarkQuery, ...]
    strategies: tuple[str, ...]
    project: str | None
    limit: int
    warmups: int
    repetitions: int
    timeout_seconds: float
    token_env: str
    output_path: Path | None
    golden_cases_path: Path | None


@dataclass(frozen=True, slots=True)
class SearchObservation:
    """One successful HTTP search observation."""

    elapsed_ms: float
    status_code: int
    effective_strategy: str | None
    match_count: int
    warning_count: int
    graph_evidence_match_count: int
    response_bytes: int
    retrieved_context_ids: tuple[str, ...]
    retrieved_titles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CaseSummary:
    """Aggregated observations for one query and requested strategy."""

    query: str
    project: str | None
    requested_strategy: str
    expected_context_ids: tuple[str, ...]
    expected_titles: tuple[str, ...]
    successful_samples: int
    failed_samples: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_mean_ms: float | None
    latency_min_ms: float | None
    latency_max_ms: float | None
    response_bytes_p50: int | None
    match_count_min: int | None
    match_count_max: int | None
    warning_count_max: int | None
    graph_evidence_match_count_max: int | None
    effective_strategies: tuple[str, ...]
    retrieved_context_id_variants: tuple[tuple[str, ...], ...]
    retrieved_title_variants: tuple[tuple[str, ...], ...]
    ranking_stable: bool | None
    recall_at_1: float | None
    recall_at_3: float | None
    mean_reciprocal_rank: float | None
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyQualitySummary:
    """Equal-query-weighted retrieval quality for one requested strategy."""

    requested_strategy: str
    evaluated_cases: int
    recall_at_1: float | None
    recall_at_3: float | None
    mean_reciprocal_rank: float | None
    unstable_case_count: int


@dataclass(frozen=True, slots=True)
class BenchmarkEnvironment:
    """Execution environment recorded with the benchmark result."""

    measured_at: str
    python_version: str
    platform: str
    base_url: str
    project: str | None
    limit: int
    warmups: int
    repetitions: int
    golden_case_count: int
    golden_cases_path: str | None
    retrieval_kernel_authority: str | None
    graph_phase_timing_available: bool
    server_memory_timing_available: bool


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Serializable Context RAG benchmark report."""

    environment: BenchmarkEnvironment
    rag_status: object
    cases: tuple[CaseSummary, ...]
    quality_by_strategy: tuple[StrategyQualitySummary, ...]
