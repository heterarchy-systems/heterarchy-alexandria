"""Immutable domain read models for bounded aggregate memory cycles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
)
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleCheckpointState,
    MemoryCycleOperation,
    MemoryCyclePhaseStatus,
    MemoryCycleStatus,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryRelationType


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCycleSourceSnapshot:
    """Stable source identity and content evidence included in the plan hash."""

    context_id: str
    canonical_path: str
    content_hash: str
    source_revision: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCycleCompactSnapshot:
    """Current Memory Compact identity and source provenance at planning time."""

    compact_id: str
    content_hash: str
    source_set_hash: str | None
    status: MemoryCompactStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCycleCandidate:
    """One typed candidate bucket item derived from an existing child plan."""

    context_id: str
    title: str
    canonical_path: str
    content_hash: str
    relation: MemoryRelationType | None
    target_context_ids: tuple[str, ...]
    child_plan_key: str | None
    reason: str
    requires_review: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCycleCompactChange:
    """Typed compact publication candidate and review outcome."""

    status: MemoryCompactStatus | None
    compact_id: str | None
    content_hash: str | None
    source_set_hash: str | None
    review_verdict: MemoryCompactReviewVerdict | None
    safe_to_publish: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCycleBuckets:
    """Explicit bounded candidate buckets returned by dry-run and apply."""

    retained_facts: tuple[MemoryCycleCandidate, ...] = ()
    duplicates: tuple[MemoryCycleCandidate, ...] = ()
    supersession_candidates: tuple[MemoryCycleCandidate, ...] = ()
    contradictions: tuple[MemoryCycleCandidate, ...] = ()
    compact_changes: tuple[MemoryCycleCompactChange, ...] = ()
    summary_candidates: tuple[MemoryCycleCandidate, ...] = ()
    relationship_changes: tuple[MemoryCycleCandidate, ...] = ()
    archive_candidates: tuple[MemoryCycleCandidate, ...] = ()
    review_required: tuple[MemoryCycleCandidate, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCyclePhase:
    """Phase-level evidence for non-atomic aggregate execution."""

    name: str
    status: MemoryCyclePhaseStatus
    detail: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCycleChildOutcome:
    """Durable child-plan admission/apply evidence."""

    child_plan_key: str
    plan_id: str | None
    result_id: str | None
    relation: MemoryRelationType
    status: str
    requires_review: bool
    warnings: tuple[str, ...] = ()
    affected_context_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCycleResult:
    """Agent-facing result for one memory-cycle operation."""

    operation: MemoryCycleOperation
    status: MemoryCycleStatus
    idempotency_key: str
    plan_hash: str
    project: str
    workspace_id: str | None
    scope: str | None
    window_start: datetime
    window_end: datetime
    replayed: bool
    scanned: int
    total_available: int
    candidate_count: int
    source_snapshot: tuple[MemoryCycleSourceSnapshot, ...]
    current_compact: MemoryCycleCompactSnapshot | None
    buckets: MemoryCycleBuckets
    child_outcomes: tuple[MemoryCycleChildOutcome, ...]
    compact_change: MemoryCycleCompactChange | None
    phases: tuple[MemoryCyclePhase, ...]
    warnings: tuple[str, ...]
    elapsed_ms: float
    query_count: int | None = None
    hard_delete_performed: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCycleCheckpoint:
    """Typed report-bundle checkpoint for exact cycle replay."""

    idempotency_key: str
    plan_hash: str
    state: MemoryCycleCheckpointState
    result: MemoryCycleResult
    source_snapshot: tuple[MemoryCycleSourceSnapshot, ...]
    compact_id: str | None
    child_plan_ids: tuple[str, ...]
    child_result_ids: tuple[str | None, ...]
