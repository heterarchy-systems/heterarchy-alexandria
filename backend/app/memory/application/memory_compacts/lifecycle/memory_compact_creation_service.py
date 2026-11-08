"""Idempotent Memory Compact creation service."""

from __future__ import annotations

from dataclasses import replace

from app.memory.application.memory_compacts.lifecycle.memory_compact_candidate import (
    candidate_compact,
    normalized_create,
    with_review_metadata,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_policy import (
    ensure_current_sources_publishable,
    ensure_review_passes,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_signature import (
    compact_signature,
    create_signature,
)
from app.memory.application.memory_compacts.review.memory_compact_review import (
    review_memory_compact,
)
from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactSourceReader,
)
from app.memory.application.memory_compacts.review.memory_compact_source_reader import (
    read_current_source_observations,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_creation_repository import (
    IMemoryCompactCreationRepository,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
)


class MemoryCompactCreationService:
    """Create normalized Memory Compacts with stable duplicate detection."""

    def __init__(
        self,
        repository: IMemoryCompactCreationRepository,
        source_reader: MemoryCompactSourceReader | None = None,
    ) -> None:
        """Create the Memory Compact creation service.

        Args:
            repository: Persistence port for Memory Compact artifacts.
            source_reader: Owning source reader used for current evidence.
        """
        self._repository = repository
        self._source_reader = source_reader

    async def create(self, payload: MemoryCompactCreate) -> MemoryCompact:
        """Create one compact while enforcing lifecycle and idempotency rules.

        Args:
            payload: Validated Memory Compact creation contract.

        Returns:
            Created or deduplicated Memory Compact entity.
        """
        normalized = normalized_create(payload)
        async with self._repository.creation_guard():
            if normalized.status is MemoryCompactStatus.CURRENT:
                normalized = await self._review_current(normalized)
            existing = await self._find_existing_by_signature(normalized)
            if existing is not None:
                return replace(existing, deduplicated=True)
            return await self._repository.create(normalized)

    async def _review_current(
        self, payload: MemoryCompactCreate
    ) -> MemoryCompactCreate:
        """Review a legacy CURRENT create candidate under the creation lock.

        Args:
            payload: Normalized CURRENT creation payload to review.

        Returns:
            Creation payload enriched with verified review metadata.
        """
        candidate = candidate_compact(payload)
        observations = await read_current_source_observations(
            candidate,
            self._source_reader,
        )
        ensure_current_sources_publishable(observations)
        review = review_memory_compact(candidate, source_observations=observations)
        ensure_review_passes(review)
        return with_review_metadata(payload, review)

    async def _find_existing_by_signature(
        self,
        payload: MemoryCompactCreate,
    ) -> MemoryCompact | None:
        """Find existing by signature.

        Args:
            payload: Validated payload for this operation.

        Returns:
            Matched existing by signature.
        """
        signature = create_signature(payload)
        compacts = await self._repository.creation_snapshot(
            project=payload.project,
            status=payload.status,
        )
        return next(
            (
                compact
                for compact in compacts
                if compact_signature(compact) == signature
            ),
            None,
        )
