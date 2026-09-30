"""Internal typed contracts for bounded maintenance jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterOutcomeClass,
    MaintenanceDeadLetterRetirementClassification,
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.types.extra_types import JSONValue


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceJobRequest:
    """Validated request passed from an external boundary to the queue."""

    kind: MaintenanceJobKind
    requested_by: str
    source_id: str
    limit: int
    force: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingReindexJobResult:
    """Bounded result payload produced by one embedding reindex batch."""

    scanned: int
    updated: int
    skipped: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchNoteWriteJobItem:
    """One per-item CAS outcome inside an async batch note write job."""

    path: str
    status: str
    content_hash: str | None = None
    current_content_hash: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchNoteWriteJobResult:
    """Bounded per-item outcome of one async batch note write job."""

    succeeded: int
    conflicted: int
    failed: int
    items: tuple[BatchNoteWriteJobItem, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceJobSnapshot:
    """Operator-visible lifecycle snapshot for one queued job."""

    job_id: str
    kind: MaintenanceJobKind
    status: MaintenanceJobStatus
    requested_by: str
    source_id: str
    limit: int
    force: bool
    attempts: int
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stream_id: str | None = None
    deduplicated: bool = False
    error_summary: str | None = None
    attempt_history: tuple[MaintenanceJobAttempt, ...] = field(default_factory=tuple)
    result: EmbeddingReindexJobResult | BatchNoteWriteJobResult | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceQueueSnapshot:
    """Bounded Redis Streams backlog and consumer evidence."""

    stream_length: int
    pending: int
    consumers: int
    dead_letter_length: int


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceDeadLetterEntry:
    """One terminal job failure recorded in the dead-letter stream."""

    entry_id: str
    job_id: str
    kind: MaintenanceJobKind
    attempts: int
    failed_at: datetime
    error_summary: str
    source_stream_id: str
    lifecycle: str = "ACTIVE"
    attempt_history: tuple[MaintenanceJobAttempt, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceJobAttempt:
    """One bounded execution attempt retained for DLQ provenance."""

    attempt: int
    status: str
    occurred_at: datetime
    error_summary: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceDeadLetterContext:
    """Exact DLQ entry plus the Redis-owned source evidence."""

    entry: MaintenanceDeadLetterEntry
    original_job: MaintenanceJobSnapshot | None
    source_request: MaintenanceJobRequest | None
    source_stream_fields: dict[str, str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceDeadLetterInspection:
    """Operator-facing, evidence-scoped inspection result."""

    entry: MaintenanceDeadLetterEntry
    original_job: MaintenanceJobSnapshot | None
    source_request: MaintenanceJobRequest | None
    source_payload: dict[str, JSONValue] | None
    idempotency_keys: tuple[str, ...]
    effect_identities: tuple[str, ...]
    source_identity: str
    retryable: bool
    outcome_class: MaintenanceDeadLetterOutcomeClass
    recommended_action: str
    error_history: tuple[str, ...] = field(default_factory=tuple)
    retired: bool = False
    archive_id: str | None = None
    retirement_reason: str | None = None
    retirement_classification: MaintenanceDeadLetterRetirementClassification | None = (
        None
    )
    retired_by: str | None = None
    retired_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceDeadLetterRetryResult:
    """Result of a dry-run or same-ID DLQ retry request."""

    entry_id: str
    job_id: str
    dry_run: bool
    retryable: bool
    status: MaintenanceJobStatus | None = None
    snapshot: MaintenanceJobSnapshot | None = None
    reason: str = ""
    outcome_class: MaintenanceDeadLetterOutcomeClass = (
        MaintenanceDeadLetterOutcomeClass.DEFINITIVE_FAILURE
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceDeadLetterReconcileItem:
    """One normalized batch item receipt verdict."""

    index: int
    idempotency_key: str
    effect_identity: str
    status: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    canonical_path: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceDeadLetterReconcileResult:
    """Per-item receipt reconciliation without implicit queue mutation."""

    entry_id: str
    job_id: str
    outcome_class: MaintenanceDeadLetterOutcomeClass
    retryable: bool
    items: tuple[MaintenanceDeadLetterReconcileItem, ...] = field(default_factory=tuple)
    recommended_action: str = ""
    source_available: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceDeadLetterRetireResult:
    """Durable provenance and exact cleanup result for one DLQ entry."""

    entry_id: str
    job_id: str
    archive_id: str
    retired_by: str
    retired_at: datetime
    reason: str
    classification: MaintenanceDeadLetterRetirementClassification
    retired: bool
    pending_cleanup: bool = False
