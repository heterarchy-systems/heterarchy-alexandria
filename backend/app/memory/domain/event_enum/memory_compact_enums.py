"""Memory Compact enum definitions."""

from __future__ import annotations

from enum import StrEnum


class MemoryCompactStatus(StrEnum):
    """Lifecycle state for one Memory Compact."""

    DRAFT = "DRAFT"
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class MemoryCompactReviewVerdict(StrEnum):
    """Quality review verdict for Memory Compact gates."""

    PASS = "pass"
    NEEDS_REVISION = "needs_revision"
    BLOCKED = "blocked"
