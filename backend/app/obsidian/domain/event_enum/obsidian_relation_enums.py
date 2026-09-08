"""Lifecycle states for the high-level Obsidian relation operation."""

from __future__ import annotations

from enum import StrEnum


class ObsidianRelateCompletionStatus(StrEnum):
    """Truthful completion states for one durable relation mutation."""

    COMPLETED = "COMPLETED"
    REPLAYED = "REPLAYED"
    STORED_WITH_PROJECTION_WARNINGS = "STORED_WITH_PROJECTION_WARNINGS"
