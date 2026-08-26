"""Internal domain entities for durable memory reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.memory.domain.contracts.memory_reconciliation_candidate_compute_contracts import (
    ReconciliationCandidateComputeMetrics,
    ReconciliationCandidateEvidence,
)
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryClaimPolarity,
    MemoryCompactFactCategory,
    MemoryCompactSafetyIssue,
    MemoryConflictStatus,
    MemoryDecisionSource,
    MemoryReconciliationActionType,
    MemoryReconciliationFailureCode,
    MemoryReconciliationStatus,
    MemoryRelationType,
    MemoryTemporalRecallMode,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalClaimQualifier:
    """One named qualifier attached to a canonical memory claim."""

    name: str
    value: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalClaim:
    """Normalized proposition used for deterministic memory comparison."""

    subject: str
    predicate: str
    object: str
    qualifiers: tuple[CanonicalClaimQualifier, ...] = ()
    scope: ContextScope = ContextScope.PROJECT
    project: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    polarity: MemoryClaimPolarity = MemoryClaimPolarity.POSITIVE


@dataclass(frozen=True, slots=True, kw_only=True)
class MemorySourceReference:
    """Stable provenance reference carried by a memory candidate."""

    source_type: str
    source_id: str
    title: str
    detail_path: str
    source_hash: str | None = None
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCandidate:
    """Validated memory proposal before reconciliation policy is applied."""

    candidate_id: str
    title: str
    body: str
    canonical_claims: tuple[CanonicalClaim, ...]
    scope: ContextScope
    project: str | None
    tags: tuple[str, ...]
    source_refs: tuple[MemorySourceReference, ...]
    recorded_at: datetime
    observed_at: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None
    requested_lifecycle: str
    content_hash: str
    workspace_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    source_identity: str | None = None
    graph_neighbors: tuple[str, ...] = ()
    lineage_ancestors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryTemporalState:
    """Temporal and conflict overlay for one stored Context."""

    context_id: str
    recorded_at: datetime
    observed_at: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None
    is_current: bool
    conflict_set_ids: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    relation_summary: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryRelationScores:
    """Independent comparison axes used to explain relation selection."""

    semantic_similarity: float
    claim_overlap: float
    scope_compatibility: float
    temporal_compatibility: float
    source_independence: float
    polarity_conflict: float
    specificity_change: float
    freshness: float


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryRelationDecision:
    """One relation decision between a candidate and an existing Context."""

    candidate_id: str
    existing_context_id: str
    relation: MemoryRelationType
    confidence: float
    reason: str
    evidence_refs: tuple[MemorySourceReference, ...]
    claim_matches: tuple[str, ...]
    scores: MemoryRelationScores
    decision_source: MemoryDecisionSource
    policy_version: str
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryReconciliationAction:
    """One explicit state transition in a reconciliation plan."""

    action_type: MemoryReconciliationActionType
    target_context_id: str | None
    relation: MemoryRelationType | None
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryEvolutionCandidateEvidence:
    """Rust-computed proposal evidence retained without assigning final semantics."""

    compute_authority: str
    candidate_item_id: str
    compared_context_ids: tuple[str, ...]
    candidate_pairs: tuple[ReconciliationCandidateEvidence, ...]
    metrics: ReconciliationCandidateComputeMetrics


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryReconciliationPlan:
    """Complete, non-mutating plan produced before reconciliation apply."""

    plan_id: str
    candidate: MemoryCandidate
    decisions: tuple[MemoryRelationDecision, ...]
    primary_decision: MemoryRelationType
    actions: tuple[MemoryReconciliationAction, ...]
    warnings: tuple[str, ...]
    conflicting_context_ids: tuple[str, ...]
    requires_review: bool
    idempotency_key: str
    status: MemoryReconciliationStatus
    created_at: datetime
    candidate_evidence: MemoryEvolutionCandidateEvidence | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryConflictSet:
    """Durable set of claims that cannot be safely collapsed into one fact."""

    conflict_set_id: str
    context_ids: tuple[str, ...]
    candidate_id: str
    subject_key: str
    claim_key: str
    scope: ContextScope
    validity_overlap: bool
    reason: str
    status: MemoryConflictStatus
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryReconciliationResult:
    """Auditable outcome of applying one reconciliation plan."""

    reconciliation_id: str
    plan_id: str
    status: MemoryReconciliationStatus
    created_context_ids: tuple[str, ...] = ()
    updated_context_ids: tuple[str, ...] = ()
    superseded_context_ids: tuple[str, ...] = ()
    created_relation_ids: tuple[str, ...] = ()
    created_conflict_set_ids: tuple[str, ...] = ()
    merged_evidence: tuple[MemorySourceReference, ...] = ()
    review_queue_item_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    hard_delete_performed: bool = False
    failure_code: MemoryReconciliationFailureCode | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryRecallCandidate:
    """Existing Context prepared for reconciliation-specific comparison."""

    context_id: str
    title: str
    body: str
    canonical_claims: tuple[CanonicalClaim, ...]
    scope: ContextScope
    project: str | None
    source_identity: str | None
    content_hash: str
    recorded_at: datetime
    observed_at: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None
    workspace_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    source_refs: tuple[MemorySourceReference, ...] = ()
    recall_reasons: tuple[str, ...] = field(default_factory=tuple)
    graph_neighbors: tuple[str, ...] = ()
    lineage_ancestors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryRelationRecord:
    """Persisted directed relation between two durable Context records."""

    relation_id: str
    source_context_id: str
    target_context_id: str
    candidate_id: str
    relation: MemoryRelationType
    confidence: float
    reason: str
    decision_source: MemoryDecisionSource
    policy_version: str
    evidence_refs: tuple[MemorySourceReference, ...]
    claim_matches: tuple[str, ...]
    scores: MemoryRelationScores
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryTemporalRecallMatch:
    """One Context search match enriched with temporal reconciliation state."""

    match: ContextSearchMatch
    temporal_state: MemoryTemporalState | None
    is_current: bool
    conflict_set_ids: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    relation_summary: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryTemporalRecallPack:
    """Context recall result viewed from a current, historical, or all-state lens."""

    query: str
    mode: MemoryTemporalRecallMode
    as_of: datetime | None
    strategy: RagStrategy
    effective_strategy: RagStrategy
    warnings: tuple[str, ...]
    recall_scopes: tuple[ContextScope, ...]
    matches: tuple[MemoryTemporalRecallMatch, ...]
    context_pack: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompactFact:
    """One Context fact classified for safe Memory Compact generation."""

    context_id: str
    title: str
    content: str
    category: MemoryCompactFactCategory
    valid_from: datetime | None
    valid_to: datetime | None
    evidence_refs: tuple[str, ...]
    conflict_set_ids: tuple[str, ...]
    relation_summary: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompactFactBuckets:
    """Structured facts that must not be collapsed across temporal states."""

    current_facts: tuple[MemoryCompactFact, ...] = ()
    historical_facts: tuple[MemoryCompactFact, ...] = ()
    open_conflicts: tuple[MemoryCompactFact, ...] = ()
    uncertain_claims: tuple[MemoryCompactFact, ...] = ()
    superseded_facts: tuple[MemoryCompactFact, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompactSafetyReview:
    """Safety review result for reconciliation-aware Memory Compact input."""

    buckets: MemoryCompactFactBuckets
    issues: tuple[MemoryCompactSafetyIssue, ...]
    safe_to_publish: bool
    warnings: tuple[str, ...]
    rendered_markdown: str
