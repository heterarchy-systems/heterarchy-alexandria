"""Validated internal contracts for Memory Compact persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompactSourceRefCreate:
    """Source ref fields accepted during compact creation."""

    source_type: str
    source_id: str
    title: str
    detail_path: str
    source_hash: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompactCreate:
    """Fields required to create a Memory Compact."""

    project: str | None
    covered_from: datetime
    covered_to: datetime
    markdown_body: str
    status: MemoryCompactStatus
    source_refs: tuple[MemoryCompactSourceRefCreate, ...]
    review_verdict: MemoryCompactReviewVerdict | None = None
    review_score: int | None = None
    review_max_score: int | None = None
    reviewed_at: datetime | None = None

    def __post_init__(self) -> None:
        """Normalize source references to the immutable internal representation."""
        object.__setattr__(self, "source_refs", tuple(self.source_refs))
