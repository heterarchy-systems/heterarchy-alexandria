"""Redis-backed maintenance job lifecycle enums."""

from __future__ import annotations

from enum import StrEnum


class MaintenanceJobKind(StrEnum):
    """Maintenance operations accepted by the bounded worker."""

    EMBEDDING_REINDEX = "embedding_reindex"
    BATCH_NOTE_WRITE = "batch_note_write"


class MaintenanceJobStatus(StrEnum):
    """Observable lifecycle states for one maintenance job."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
