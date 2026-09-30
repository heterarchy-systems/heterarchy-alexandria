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


class MaintenanceDeadLetterOutcomeClass(StrEnum):
    """Evidence class used before a dead-letter operation is selected."""

    DEFINITIVE_FAILURE = "DEFINITIVE_FAILURE"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    CONFLICT = "CONFLICT"
    NON_RETRYABLE = "NON_RETRYABLE"
    OBSOLETE = "OBSOLETE"


class MaintenanceDeadLetterRetirementClassification(StrEnum):
    """Bounded operator classification recorded in a retirement archive."""

    OBSOLETE = "OBSOLETE"
    SUPERSEDED = "SUPERSEDED"
    INVALID_SOURCE = "INVALID_SOURCE"
    MANUAL_RECONCILED = "MANUAL_RECONCILED"
    NON_RETRYABLE = "NON_RETRYABLE"
    HISTORICAL_RESIDUAL = "HISTORICAL_RESIDUAL"
