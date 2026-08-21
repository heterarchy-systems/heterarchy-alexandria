"""Idempotent Memory Compact creation service."""

from __future__ import annotations

from dataclasses import replace

from app.memory.application.memory_compacts.lifecycle.memory_compact_candidate import (
    normalized_create,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_signature import (
    compact_signature,
    create_signature,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.repositories.memory_compacts.memory_compact_creation_repository import (
    IMemoryCompactCreationRepository,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
)


class MemoryCompactCreationService:
    """Create normalized Memory Compacts with stable duplicate detection."""

    def __init__(self, repository: IMemoryCompactCreationRepository) -> None:
        """Create the Memory Compact creation service.

        Args:
            repository: Persistence port for Memory Compact artifacts.
        """
        self._repository = repository

    async def create(self, payload: MemoryCompactCreate) -> MemoryCompact:
        """Create one compact while enforcing lifecycle and idempotency rules.

        Args:
            payload: Validated Memory Compact creation contract.

        Returns:
            Created or deduplicated Memory Compact entity.
        """
        normalized = normalized_create(payload)
        async with self._repository.creation_guard():
            existing = await self._find_existing_by_signature(normalized)
            if existing is not None:
                return replace(existing, deduplicated=True)
            return await self._repository.create(normalized)

    async def _find_existing_by_signature(
        self,
        payload: MemoryCompactCreate,
    ) -> MemoryCompact | None:
        signature = create_signature(payload)
        offset = 0
        while True:
            compacts, total = await self._repository.list_compacts(
                project=payload.project,
                limit=200,
                offset=offset,
            )
            for compact in compacts:
                if compact_signature(compact) == signature:
                    return compact
            if not compacts or offset + len(compacts) >= total:
                return None
            offset += len(compacts)
