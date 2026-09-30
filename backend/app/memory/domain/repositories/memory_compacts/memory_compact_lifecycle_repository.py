"""Lifecycle persistence port for Memory Compact artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactReviewVerdict


class IMemoryCompactLifecycleRepository(ABC):
    """Promote, archive, and explicitly remove Memory Compact artifacts."""

    async def edit_draft(
        self, compact_id: str, markdown_body: str, expected_state_hash: str
    ) -> MemoryCompact:
        """Replace a DRAFT body behind its exact snapshot fence.

        Args:
            compact_id: Existing DRAFT identity.
            markdown_body: Caller-reviewed semantic replacement.
            expected_state_hash: Last observed draft state digest.

        Returns:
            Edited draft with previous review evidence invalidated.
        """
        raise NotImplementedError("Draft editing is not supported by this source owner")

    @abstractmethod
    async def mark_current(
        self,
        compact_id: str,
        review_verdict: MemoryCompactReviewVerdict | None = None,
        review_score: int | None = None,
        review_max_score: int | None = None,
        reviewed_at: datetime | None = None,
        expected_state_hash: str | None = None,
        reviewed_body_hash: str | None = None,
        review_receipt_hash: str | None = None,
    ) -> MemoryCompact:
        """Mark one compact current and supersede previous current.

        Args:
            compact_id: Memory Compact identifier.
            review_verdict: Latest quality review verdict for the promotion.
            review_score: Latest quality review total score.
            review_max_score: Latest quality review maximum score.
            reviewed_at: Review timestamp.
            reviewed_body_hash: Exact reviewed body identity.
            review_receipt_hash: Admitted review identity.
            expected_state_hash: Hash of the exact target state reviewed before
                persistence; a mismatch rejects promotion.

        Returns:
            Updated current compact.
        """

    @abstractmethod
    async def archive(self, compact_id: str) -> MemoryCompact:
        """Archive one compact.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Archived compact.
        """

    @abstractmethod
    async def delete(self, compact_id: str) -> None:
        """Explicitly remove one compact and dependent source refs.

        Args:
            compact_id: Memory Compact identifier.
        """
