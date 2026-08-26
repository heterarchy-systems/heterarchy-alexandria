"""Typed contracts for the Alexandria Memory Evaluation Suite."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemoryEvalQueryClass(StrEnum):
    """Stable query classes covered by the durable memory benchmark."""

    EXACT_LOOKUP = "EXACT_LOOKUP"
    SEMANTIC_PARAPHRASE = "SEMANTIC_PARAPHRASE"
    CROSS_LANGUAGE = "CROSS_LANGUAGE"
    TEMPORAL_CURRENT_STATE = "TEMPORAL_CURRENT_STATE"
    SUPERSESSION = "SUPERSESSION"
    CONFLICT_PRESERVATION = "CONFLICT_PRESERVATION"
    EXPERIENTIAL_RECALL = "EXPERIENTIAL_RECALL"
    PROCEDURAL_RECALL = "PROCEDURAL_RECALL"
    MULTI_HOP_GRAPH = "MULTI_HOP_GRAPH"
    WRONG_PREMISE = "WRONG_PREMISE"
    UNKNOWN_ABSTENTION = "UNKNOWN_ABSTENTION"


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryEvalCase:
    """One explicit versioned memory-evaluation truth case."""

    case_id: str
    query: str
    query_class: MemoryEvalQueryClass
    project: str | None
    include_scopes: tuple[str, ...]
    include_lifecycle_statuses: tuple[str, ...]
    expected_context_ids: tuple[str, ...]
    expected_titles: tuple[str, ...]
    forbidden_context_ids: tuple[str, ...]
    forbidden_titles: tuple[str, ...]
    required_graph_relations: tuple[str, ...]
    minimum_graph_distance: int
    minimum_expected_matches: int
    expected_abstention: bool
    rationale: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryEvalObservation:
    """One read-only search observation used by memory-specific metrics."""

    elapsed_ms: float
    effective_strategy: str | None
    retrieved_context_ids: tuple[str, ...]
    retrieved_titles: tuple[str, ...]
    retrieved_lifecycle_statuses: tuple[str | None, ...]
    graph_relations: tuple[str, ...]
    graph_max_distance: int
    warning_count: int
    response_bytes: int

    @property
    def match_count(self) -> int:
        """Return the number of ranked matches observed.

        Returns:
            Maximum aligned identity/title result length.
        """
        return max(len(self.retrieved_context_ids), len(self.retrieved_titles))


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryEvalCaseMetrics:
    """Quality metrics for one case aggregated across repeated observations."""

    case_id: str
    query_class: MemoryEvalQueryClass
    requested_strategy: str
    observation_count: int
    failure_count: int
    ranking_stable: bool | None
    recall_at_1: float | None
    recall_at_3: float | None
    recall_at_5: float | None
    mean_reciprocal_rank: float | None
    ndcg_at_5: float | None
    temporal_correctness: float | None
    obsolete_memory_rate: float | None
    superseded_memory_leakage_rate: float | None
    historical_current_precision: float | None
    experiential_recall_success_rate: float | None
    procedural_recall_success_rate: float | None
    wrong_premise_correction_rate: float | None
    conflict_collapse_rate: float | None
    wrong_memory_rate: float | None
    abstention_accuracy: float | None
    multi_hop_success_rate: float | None
    cross_language_success_rate: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    effective_strategies: tuple[str, ...]
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryEvalStrategyMetrics:
    """Equal-case-weighted memory quality summary for one retrieval strategy."""

    requested_strategy: str
    evaluated_cases: int
    recall_at_1: float | None
    recall_at_3: float | None
    recall_at_5: float | None
    mean_reciprocal_rank: float | None
    ndcg_at_5: float | None
    temporal_correctness: float | None
    obsolete_memory_rate: float | None
    superseded_memory_leakage_rate: float | None
    historical_current_precision: float | None
    experiential_recall_success_rate: float | None
    procedural_recall_success_rate: float | None
    wrong_premise_correction_rate: float | None
    conflict_collapse_rate: float | None
    wrong_memory_rate: float | None
    abstention_accuracy: float | None
    multi_hop_success_rate: float | None
    cross_language_success_rate: float | None
    unstable_case_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryEvalEnvironment:
    """Runtime evidence recorded alongside one Memory Evaluation Suite report."""

    measured_at: str
    python_version: str
    platform: str
    base_url: str
    corpus_path: str
    corpus_sha256: str
    corpus_case_count: int
    strategies: tuple[str, ...]
    limit: int
    repetitions: int
    retrieval_kernel_authority: str | None
    runtime_provenance: object


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryEvalReport:
    """Serializable Memory Evaluation Suite report."""

    environment: MemoryEvalEnvironment
    cases: tuple[MemoryEvalCaseMetrics, ...]
    quality_by_strategy: tuple[MemoryEvalStrategyMetrics, ...]
