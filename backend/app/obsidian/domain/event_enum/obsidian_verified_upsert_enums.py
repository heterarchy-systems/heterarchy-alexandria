"""Enum contracts for verified Obsidian upsert operations and checkpoints."""

from __future__ import annotations

from enum import StrEnum


class ObsidianVerifiedUpsertOperation(StrEnum):
    """Observed logical operation for one verified upsert."""

    CREATED = "created"
    UPDATED = "updated"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class ObsidianVerifiedProjectionStatus(StrEnum):
    """Evidence status for one source or derived projection."""

    UNKNOWN = "unknown"
    PENDING = "pending"
    STALE = "stale"
    VERIFIED = "verified"
    UNAVAILABLE = "unavailable"


class ObsidianVerifiedDuplicateSafety(StrEnum):
    """Logical-identity duplicate safety evidence."""

    VERIFIED = "verified"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class ObsidianVerifiedCheckpointState(StrEnum):
    """Durable phases used to recover a verified upsert after interruption."""

    INTENT_RECORDED = "intent_recorded"
    WRITE_STARTED = "write_started"
    COMPLETED = "completed"
    UNKNOWN_OUTCOME = "unknown_outcome"
