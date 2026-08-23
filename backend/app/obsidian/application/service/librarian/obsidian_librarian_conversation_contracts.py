"""Read, save, and search hooks for Obsidian librarian conversations."""

from __future__ import annotations

from typing import Protocol

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianSearchQuery,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianSearchHit,
)


# protocol-contract: structural-seam
class ObsidianConversationReadHook(Protocol):
    """Read one note by vault-relative path."""

    async def __call__(self, relative_path: str) -> ObsidianNote:
        """Read one note.

        Args:
            relative_path: Relative path used by this operation.

        Returns:
            ObsidianNote result produced by call.
        """


# protocol-contract: structural-seam
class ObsidianConversationSaveHook(Protocol):
    """Persist one note through the canonical save path."""

    async def __call__(self, payload: ObsidianSaveNote) -> ObsidianNote:
        """Save one note.

        Args:
            payload: Validated payload for this operation.

        Returns:
            ObsidianNote result produced by call.
        """


# protocol-contract: structural-seam
class ObsidianConversationSearchHook(Protocol):
    """Search indexed notes for librarian evidence."""

    async def __call__(
        self,
        query: ObsidianSearchQuery,
        refresh: bool = True,
    ) -> list[ObsidianSearchHit]:
        """Search indexed notes.

        Args:
            query: Query used by this operation.
            refresh: Whether to refresh source state before the operation.

        Returns:
            list[ObsidianSearchHit] result produced by call.
        """
