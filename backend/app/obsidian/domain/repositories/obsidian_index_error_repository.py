"""Error persistence port for Obsidian index failures."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.obsidian.domain.entities.obsidian_note import ObsidianIndexError


class IObsidianIndexErrorRepository(ABC):
    """Record and read structured Obsidian indexing failures."""

    @abstractmethod
    async def record_index_error(self, error: ObsidianIndexError) -> None:
        """Persist one structured reindex error in the rebuildable index.

        Args:
            error: Structured note indexing failure.
        """

    @abstractmethod
    async def clear_index_error(self, note_path: str) -> None:
        """Remove a resolved structured error for one canonical note path.

        Args:
            note_path: Vault-relative Markdown path whose source is readable again.
        """

    @abstractmethod
    async def list_index_errors(self, limit: int = 20) -> list[ObsidianIndexError]:
        """Return recent structured reindex errors.

        Args:
            limit: Maximum number of recent errors to return.

        Returns:
            Recent structured indexing failures.
        """
