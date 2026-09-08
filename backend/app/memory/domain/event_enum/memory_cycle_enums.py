"""Symbolic values for the high-level memory-cycle contract."""

from __future__ import annotations

from enum import StrEnum


class MemoryCycleOperation(StrEnum):
    """Requested cycle phase at the public boundary."""

    DRY_RUN = "dry_run"
    APPLY = "apply"


class MemoryCycleStatus(StrEnum):
    """Aggregate lifecycle status reported by one cycle."""

    PREVIEW = "PREVIEW"
    ADMITTED = "ADMITTED"
    APPLIED = "APPLIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class MemoryCyclePhaseStatus(StrEnum):
    """Outcome of one observable cycle phase."""

    SUCCEEDED = "SUCCEEDED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class MemoryCycleCheckpointState(StrEnum):
    """Durable checkpoint state used for replay and recovery fencing."""

    ADMITTED = "ADMITTED"
    COMPLETED = "COMPLETED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
