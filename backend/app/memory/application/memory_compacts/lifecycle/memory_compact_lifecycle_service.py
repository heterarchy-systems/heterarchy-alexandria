"""Memory Compact lifecycle mutation and rubric review service."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.application.memory_compacts.lifecycle.memory_compact_policy import (
    ensure_current_sources_publishable,
    ensure_review_passes,
    missing_current_sections,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_query_service import (
    MemoryCompactQueryService,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_signature import (
    _body_hash,
    compact_state_hash,
    reviewed_compact_hash,
)
from app.memory.application.memory_compacts.review.memory_compact_review import (
    review_memory_compact,
)
from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactReviewResult,
    MemoryCompactSourceObservation,
    MemoryCompactSourceReader,
)
from app.memory.application.memory_compacts.review.memory_compact_source_reader import (
    read_current_source_observations,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.repositories.memory_compacts.memory_compact_repository import (
    IMemoryCompactRepository,
)
from app.shared.exceptions.memory_compact_exceptions import (
    MemoryCompactReviewConflictError,
    MemoryCompactValidationError,
)


class MemoryCompactLifecycleService:
    """Promote, archive, delete, and review durable Memory Compacts."""

    def __init__(
        self,
        repository: IMemoryCompactRepository,
        query_service: MemoryCompactQueryService,
        source_reader: MemoryCompactSourceReader | None = None,
    ) -> None:
        """Create the Memory Compact lifecycle service.

        Args:
            repository: Persistence port for Memory Compact artifacts.
            query_service: Canonical compact read collaborator.
            source_reader: Owning source reader used for current evidence.
        """
        self._repository = repository
        self._query_service = query_service
        self._source_reader = source_reader

    async def mark_current(
        self,
        compact_id: str,
        expected_review_hash: str | None = None,
    ) -> MemoryCompact:
        """Review and mark one compact as current.

        Args:
            compact_id: Memory Compact identifier.
            expected_review_hash: Optional reviewed-receipt hash admitted by a
                prior review; a mismatch rejects the promotion.

        Returns:
            Updated current Memory Compact entity.
        """
        async with self._repository.creation_guard():
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
            source_observations = await read_current_source_observations(
                compact,
                self._source_reader,
            )
            ensure_current_sources_publishable(source_observations)
            review = review_memory_compact(
                compact,
                source_observations=source_observations,
            )
            try:
                ensure_review_passes(review)
            except MemoryCompactValidationError as exc:
                if expected_review_hash is None:
                    raise
                raise MemoryCompactReviewConflictError(
                    "MEMORY_COMPACT_REVIEW_CONFLICT: current source evidence "
                    "changed or became unavailable after review; re-review "
                    "before applying"
                ) from exc
            review_hash = reviewed_compact_hash(
                compact,
                verdict=review.verdict.value,
                total_score=review.total_score,
                max_score=review.max_score,
                source_observations=source_observations,
            )
            if expected_review_hash is not None and expected_review_hash != review_hash:
                raise MemoryCompactReviewConflictError(
                    "MEMORY_COMPACT_REVIEW_CONFLICT: the compact body, source "
                    "evidence, or review drifted from the admitted receipt; "
                    "re-review before applying"
                )
            return await self._repository.mark_current(
                compact_id,
                review_verdict=review.verdict,
                review_score=review.total_score,
                review_max_score=review.max_score,
                reviewed_at=datetime.now(UTC),
                expected_state_hash=compact_state_hash(compact),
                reviewed_body_hash=_body_hash(compact.markdown_body),
                review_receipt_hash=review_hash,
            )

    async def archive(self, compact_id: str) -> MemoryCompact:
        """Archive one Memory Compact.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Archived Memory Compact entity.
        """
        return await self._repository.archive(compact_id)

    async def delete(self, compact_id: str, *, confirm: bool = False) -> None:
        """Hard delete one Memory Compact after explicit confirmation.

        Args:
            compact_id: Memory Compact identifier.
            confirm: Explicit hard-delete confirmation; deletion is refused
                without it.
        """
        if not confirm:
            raise MemoryCompactValidationError(
                "hard delete requires explicit confirmation"
            )
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
        async with self._repository.creation_guard():
            compact = await self._query_service.get(compact_id)
            authoritative_observations = await read_current_source_observations(
                compact,
                self._source_reader,
            )
            observations = authoritative_observations
            return review_memory_compact(
                compact,
                source_observations=observations,
            )
