"""Memory Compact read model entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompactSourceRef:
    """Source reference attached to one Memory Compact."""

    id: str
    compact_id: str
    source_type: str
    source_id: str
    title: str
    detail_path: str
    source_hash: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompact:
    """First-class durable summary of long-term project memory."""

    id: str
    project: str | None
    covered_from: datetime
    covered_to: datetime
    markdown_body: str
    status: MemoryCompactStatus
    source_refs: tuple[MemoryCompactSourceRef, ...]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    review_verdict: MemoryCompactReviewVerdict | None = None
    review_score: int | None = None
    review_max_score: int | None = None
    reviewed_at: datetime | None = None
    metadata_warnings: tuple[str, ...] = ()
    deduplicated: bool = False
    source_set_hash: str | None = None
    compaction_policy_version: str | None = None
    generation_revision: int | None = None
    generated_at: datetime | None = None

    @property
    def source_count(self) -> int:
        """Return the number of durable source references covered by this compact.

        Returns:
            Source reference count derived from canonical source refs.
        """
        return len(self.source_refs)

    @property
    def expansion_refs(self) -> tuple[str, ...]:
        """Return stable source expansion paths without persisting duplicate metadata.

        Returns:
            Distinct non-empty source detail paths in source-reference order.
        """
        return tuple(
            dict.fromkeys(
                source_ref.detail_path.strip()
                for source_ref in self.source_refs
                if source_ref.detail_path.strip()
            )
        )

    @property
    def provenance_complete(self) -> bool:
        """Return whether this compact carries the complete v2 provenance seal.

        Returns:
            True when all durable Compact 2.0 provenance fields are populated.
        """
        return (
            bool(self.source_set_hash)
            and bool(self.compaction_policy_version)
            and self.generation_revision is not None
            and self.generated_at is not None
        )
