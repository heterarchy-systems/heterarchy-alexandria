"""Typed wire records for Redis maintenance operations."""

from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import TypedDict

from app.shared.types.extra_types import JSONValue


class MaintenanceStatusFields(TypedDict, total=False, closed=True):
    """Normalized Redis hash fields for one maintenance job."""

    job_id: str
    kind: str
    status: str
    requested_by: str
    source_id: str
    limit: str
    force: str
    attempts: str
    submitted_at: str
    started_at: str
    finished_at: str
    stream_id: str
    result_json: str
    error_summary: str
    attempt_history_json: str
    last_retry_reason: str
    last_retry_at: str
    dlq_state: str


class MaintenanceDeadLetterFields(TypedDict, total=False, closed=True):
    """Normalized Redis dead-letter stream fields for one terminal failure."""

    job_id: str
    kind: str
    attempts: str
    failed_at: str
    error_summary: str
    source_stream_id: str
    lifecycle: str
    attempt_history_json: str


@dataclass(frozen=True, slots=True, kw_only=True)
class EnqueueScriptResult:
    """Normalized atomic enqueue script response."""

    state: str
    value: str
    stream_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RedisStreamDelivery:
    """Minimal decoded Redis Streams delivery."""

    stream_id: str
    job_id: str


class BatchNoteWriteJobItemPayload(TypedDict, closed=True):
    """Persisted item fields in their original JSON order."""

    path: str
    status: str
    content_hash: str | None
    current_content_hash: str | None


class BatchNoteWriteJobResultPayload(TypedDict, closed=True):
    """Persisted batch totals and item records."""

    succeeded: int
    conflicted: int
    failed: int
    items: list[dict[str, JSONValue]]


class EmbeddingReindexJobResultPayload(TypedDict, closed=True):
    """Persisted embedding totals and warnings."""

    scanned: int
    updated: int
    skipped: int
    warnings: list[str]


class MaintenanceJobAttemptPayload(TypedDict, closed=True):
    """One persisted attempt in bounded execution history."""

    attempt: int
    status: str
    occurred_at: str
    error_summary: str | None
