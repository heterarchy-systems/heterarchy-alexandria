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


class ObsidianConversationReadHook(Protocol):
    """Read one note by vault-relative path."""

    async def __call__(self, relative_path: str) -> ObsidianNote:
        """Read one note."""


class ObsidianConversationSaveHook(Protocol):
    """Persist one note through the canonical save path."""

    async def __call__(self, payload: ObsidianSaveNote) -> ObsidianNote:
        """Save one note."""


class ObsidianConversationSearchHook(Protocol):
    """Search indexed notes for librarian evidence."""

    async def __call__(
        self,
        query: ObsidianSearchQuery,
        refresh: bool = True,
    ) -> list[ObsidianSearchHit]:
        """Search indexed notes."""
