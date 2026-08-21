"""Feature-owned obsidian librarian review enums."""

from __future__ import annotations

from enum import StrEnum


class ReviewQueueStatusMarker(StrEnum):
    """Feature-owned values for ReviewQueueStatusMarker."""

    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    PENDING = "pending"
    REVIEW = "review"
    TO_PROMOTE = "to_promote"
