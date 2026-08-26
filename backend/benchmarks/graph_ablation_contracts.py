"""Typed contracts for graph depth 0/1/2 retrieval ablation evidence."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphAblationDepthObservation:
    """One graph-depth candidate-discovery observation for a truth case."""

    depth: int
    expected_hit_count: int
    expected_total: int
    success: bool
    candidate_count: int
    expanded_candidate_count: int
    unlabeled_expansion_count: int
    traversal_request_count: int
    traversal_truncated_count: int
    graph_compute_ms: float


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphAblationCaseObservation:
    """Primary retrieval seeds and graph-depth observations for one truth case."""

    case_id: str
    query: str
    primary_context_ids: tuple[str, ...]
    expected_context_ids: tuple[str, ...]
    search_ms: float
    depths: tuple[GraphAblationDepthObservation, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphAblationDepthSummary:
    """Aggregate quality/cost evidence for one graph depth."""

    depth: int
    case_count: int
    success_rate: float
    expected_recall: float
    average_candidate_count: float
    average_expanded_candidate_count: float
    unlabeled_expansion_rate: float
    truncation_rate: float
    graph_compute_p50_ms: float
    graph_compute_p95_ms: float


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphAblationReport:
    """Reproducible graph ablation report over the multi-hop truth corpus."""

    schema_version: int
    graph_compute_authority: str
    strategy: str
    search_limit: int
    graph_max_seeds: int
    graph_max_results_per_seed: int
    projection_node_count: int
    projection_edge_count: int
    projection_snapshot_ms: float
    cases: tuple[GraphAblationCaseObservation, ...]
    summaries: tuple[GraphAblationDepthSummary, ...]
