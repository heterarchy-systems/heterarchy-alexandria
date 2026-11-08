"""Redis consumer consumer enums responsibilities."""

from __future__ import annotations

from enum import StrEnum


class MaintenanceTransitionMode(StrEnum):
    """Modes accepted by the existing fenced transition script."""

    ADMIT = "ADMIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class MaintenanceTransitionReply(StrEnum):
    """Replies that authorize or reject admission and publication."""

    ADMITTED = "ADMITTED"
    REPLAYED_SUCCEEDED = "REPLAYED_SUCCEEDED"
    REPAIRED_FAILED = "REPAIRED_FAILED"
    PUBLISHED_SUCCEEDED = "PUBLISHED_SUCCEEDED"
    PUBLISHED_RETRYING = "PUBLISHED_RETRYING"
    PUBLISHED_FAILED = "PUBLISHED_FAILED"
