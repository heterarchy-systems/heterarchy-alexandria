"""Composite contract for Memory Compact persistence operations."""

from __future__ import annotations

from app.memory.domain.repositories.memory_compacts.memory_compact_creation_repository import (
    IMemoryCompactCreationRepository,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_lifecycle_repository import (
    IMemoryCompactLifecycleRepository,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)


class IMemoryCompactRepository(
    IMemoryCompactCreationRepository,
    IMemoryCompactLifecycleRepository,
):
    """Combine focused Memory Compact persistence ports for lifecycle services."""


__all__ = [
    "IMemoryCompactRepository",
    "MemoryCompactCreate",
    "MemoryCompactSourceRefCreate",
]
