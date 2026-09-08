"""Typed lifecycle and failure values for managed specification execution."""

from __future__ import annotations

from enum import StrEnum


class ManagedSpecOperation(StrEnum):
    """High-level managed-spec operation selected by the caller."""

    PREPARE = "prepare"
    COMPLETE = "complete"


class ManagedSpecPrepareStatus(StrEnum):
    """Durable prepare outcomes."""

    PREPARED = "prepared"
    REPLAYED = "replayed"


class ManagedSpecCompletionStatus(StrEnum):
    """Durable complete outcomes."""

    COMPLETED = "completed"
    REPLAYED = "replayed"


class ManagedSpecFailureCode(StrEnum):
    """Stable actionable failures at the managed-spec trust boundary."""

    SPEC_NOT_FOUND = "SPEC_NOT_FOUND"
    SPEC_NOT_READY = "SPEC_NOT_READY"
    SPEC_CONFLICT = "SPEC_CONFLICT"
    SPEC_DRIFT = "SPEC_DRIFT"
    PREPARE_REQUIRED = "PREPARE_REQUIRED"
    ENVELOPE_MISMATCH = "ENVELOPE_MISMATCH"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    OUTPUT_DRIFT = "OUTPUT_DRIFT"
    OUTPUT_NOT_READY = "OUTPUT_NOT_READY"
