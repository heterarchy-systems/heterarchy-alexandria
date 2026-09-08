"""Memory Compact lifecycle mutation and rubric review service."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.application.memory_compacts.lifecycle.memory_compact_policy import (
    ensure_review_passes,
    missing_current_sections,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_query_service import (
    MemoryCompactQueryService,
)
from app.memory.application.memory_compacts.review.memory_compact_review import (
    review_memory_compact,
)
from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactReviewResult,
    MemoryCompactSourceObservation,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.repositories.memory_compacts.memory_compact_lifecycle_repository import (
    IMemoryCompactLifecycleRepository,
)
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactValidationError


class MemoryCompactLifecycleService:
    """Promote, archive, delete, and review durable Memory Compacts."""

    def __init__(
        self,
        repository: IMemoryCompactLifecycleRepository,
        query_service: MemoryCompactQueryService,
    ) -> None:
        """Create the Memory Compact lifecycle service.

        Args:
            repository: Persistence port for Memory Compact artifacts.
            query_service: Canonical compact read collaborator.
        """
        self._repository = repository
        self._query_service = query_service

    async def mark_current(self, compact_id: str) -> MemoryCompact:
        """Review and mark one compact as current.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Updated current Memory Compact entity.
        """
        compact = await self._query_service.get(compact_id)
        if not compact.source_refs:
            raise MemoryCompactValidationError(
                "Current memory compact requires source refs"
            )
        missing_sections = missing_current_sections(compact.markdown_body)
        if missing_sections:
            raise MemoryCompactValidationError(
                "Current memory compact missing required sections: "
                + ", ".join(missing_sections)
            )
        review = review_memory_compact(compact)
        ensure_review_passes(review)
        return await self._repository.mark_current(
            compact_id,
            review_verdict=review.verdict,
            review_score=review.total_score,
            review_max_score=review.max_score,
            reviewed_at=datetime.now(UTC),
        )

    async def archive(self, compact_id: str) -> MemoryCompact:
        """Archive one Memory Compact.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Archived Memory Compact entity.
        """
        return await self._repository.archive(compact_id)

    async def delete(self, compact_id: str) -> None:
        """Hard delete one Memory Compact.

        Args:
            compact_id: Memory Compact identifier.
        """
        await self._repository.delete(compact_id)

    async def review(
        self,
        compact_id: str,
        source_observations: tuple[MemoryCompactSourceObservation, ...] = (),
    ) -> MemoryCompactReviewResult:
        """Review one Memory Compact against the quality rubric.

        Args:
            compact_id: Memory Compact identifier.
            source_observations: Optional current source evidence observations.

        Returns:
            Structured review result.
        """
        compact = await self._query_service.get(compact_id)
        return review_memory_compact(
            compact,
            source_observations=source_observations,
        )
