"""Typed contracts for bulk reconciliation candidate discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReconciliationCandidateComputePolicy:
    """Bounded candidate-generation thresholds and cardinality limits."""

    vector_similarity_threshold: float = 0.8
    graph_similarity_threshold: float = 0.5
    max_block_size: int = 256
    max_candidates_per_item: int = 20


@dataclass(frozen=True, slots=True)
class ReconciliationCandidateComputeItem:
    """One typed item supplied to bulk candidate discovery."""

    item_id: str
    content_hash: str | None = None
    embedding: tuple[float, ...] | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    blocking_keys: tuple[str, ...] = field(default_factory=tuple)
    graph_neighbors: tuple[str, ...] = field(default_factory=tuple)
    lineage_ancestors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ReconciliationExactDuplicateGroup:
    """One exact content-hash duplicate group."""

    content_hash: str
    item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationCandidateEvidence:
    """One evidence-rich pair without final reconciliation semantics."""

    left_id: str
    right_id: str
    exact_content_hash: bool
    vector_similarity: float | None
    temporal_overlap: bool
    graph_similarity: float
    lineage: str
    candidate_score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationCandidateCluster:
    """One deterministic connected candidate group."""

    cluster_index: int
    item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationCandidateComputeMetrics:
    """Bounded-work metrics emitted by candidate discovery."""

    input_items: int
    comparison_pairs: int
    qualifying_pairs: int
    retained_pairs: int
    exact_duplicate_groups: int


@dataclass(frozen=True, slots=True)
class ReconciliationCandidateComputeResult:
    """Pure compute result consumed by Python-owned reconciliation policy."""

    exact_duplicate_groups: tuple[ReconciliationExactDuplicateGroup, ...]
    candidate_pairs: tuple[ReconciliationCandidateEvidence, ...]
    clusters: tuple[ReconciliationCandidateCluster, ...]
    metrics: ReconciliationCandidateComputeMetrics
