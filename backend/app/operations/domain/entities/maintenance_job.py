"""Internal typed contracts for bounded maintenance jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
    MaintenanceJobStatus,
)


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
    result: EmbeddingReindexJobResult | None = None


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
