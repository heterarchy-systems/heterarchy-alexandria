"""Write persistence port for the rebuildable Obsidian note index."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianCompiledDocumentState,
    ObsidianNoteIndex,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote


class IObsidianIndexWriteRepository(ABC):
    """Mutate rebuildable PostgreSQL note index state."""

    @abstractmethod
    async def upsert_note(self, payload: ObsidianNoteIndex) -> ObsidianNote:
        """Create or update one indexed note and its chunks.

        Args:
            payload: Indexed note payload.

        Returns:
            Persisted note entity.
        """

    @abstractmethod
    async def list_indexed_note_identifiers(self) -> tuple[tuple[str, str], ...]:
        """Return every indexed note identity in the rebuildable projection.

        Returns:
            (note_id, relative_path) pairs for all indexed notes.
        """

    @abstractmethod
    async def list_compiled_document_states(
        self,
    ) -> tuple[ObsidianCompiledDocumentState, ...]:
        """Return previous deterministic compile state for every indexed note."""

    @abstractmethod
    async def read_compiled_embedding_fingerprint_key(self) -> str | None:
        """Return one complete persisted embedding generation, if one exists."""

    @abstractmethod
    async def mark_documents_stale(self, relative_paths: tuple[str, ...]) -> int:
        """Discard indexed notes removed from the canonical scan.

        Args:
            relative_paths: Paths removed per the compile plan.

        Returns:
            Number of note indexes discarded.
        """
