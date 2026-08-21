"""Canonical Obsidian Context archive and supersede orchestration."""

from __future__ import annotations

from typing import Protocol

from app.obsidian.application.notes.lifecycle.obsidian_context_lifecycle import (
    ObsidianContextLifecycleCoordinator as ContextLifecycleEngine,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)


class ObsidianContextReadHook(Protocol):
    """Read one canonical Context note by id."""

    async def __call__(self, note_id: str) -> ObsidianNote:
        """Read one Context note.

        Args:
            note_id: Canonical Context note identifier.

        Returns:
            Canonical Context note.
        """


class ObsidianContextLifecycleService:
    """Own Context archive and supersede use cases over canonical Markdown."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_config_store: ObsidianVaultConfigStore,
        read_note: ObsidianContextReadHook,
    ) -> None:
        """Create the Context lifecycle service.

        Args:
            repository: Rebuildable PostgreSQL index repository.
            vault_config_store: Runtime vault location provider.
            read_note: Canonical note read callback.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._read_note = read_note

    async def archive(self, note_id: str) -> ObsidianNote:
        """Archive one canonical Context while preserving Markdown.

        Args:
            note_id: Canonical Context note identifier.

        Returns:
            Reindexed archived Context note.
        """
        note = await self._read_note(note_id)
        return await self._engine().archive(note)

    async def supersede(
        self,
        note_id: str,
        replacement_note_id: str,
    ) -> tuple[ObsidianNote, ObsidianNote]:
        """Link an existing Context to an existing replacement.

        Args:
            note_id: Canonical Context identifier to supersede.
            replacement_note_id: Canonical replacement Context identifier.

        Returns:
            Superseded and replacement canonical notes.
        """
        superseded = await self._read_note(note_id)
        replacement = await self._read_note(replacement_note_id)
        return await self._engine().supersede(superseded, replacement)

    async def mark_superseded(
        self,
        superseded_context_id: str,
        replacement_context_id: str,
    ) -> None:
        """Update one Context backlink during save or reindex reconciliation.

        Args:
            superseded_context_id: Context being replaced.
            replacement_context_id: Canonical replacement Context.
        """
        await self._engine().mark_superseded(
            superseded_context_id,
            replacement_context_id,
        )

    def _engine(self) -> ContextLifecycleEngine:
        config = self._vault_config_store.current()
        return ContextLifecycleEngine(
            self._repository,
            config.vault_path,
            config.alexandria_root,
        )
