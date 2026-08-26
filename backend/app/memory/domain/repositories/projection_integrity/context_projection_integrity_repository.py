"""Persistence port for the rebuildable Context projection integrity snapshot."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.context_projection_integrity import (
    ContextProjectionIntegritySnapshot,
)


class IContextProjectionIntegrityRepository(ABC):
    """Persist and read the latest Obsidian-to-Context projection scan."""

    @abstractmethod
    async def get_latest(self) -> ContextProjectionIntegritySnapshot | None:
        """Return the latest persisted projection-integrity snapshot when present.

        Returns:
            Latest singleton snapshot, or None when no scan has been persisted.
        """

    @abstractmethod
    async def replace_latest(
        self, snapshot: ContextProjectionIntegritySnapshot
    ) -> None:
        """Replace the singleton projection-integrity snapshot atomically.

        Args:
            snapshot: Complete projection-integrity snapshot to persist.
        """
