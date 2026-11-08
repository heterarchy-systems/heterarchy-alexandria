"""Own vault configuration, initialization, status, and index-lifecycle admission."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol

from typing_extensions import TypedDict

from app.obsidian.application.notes.obsidian_note_templates import (
    default_folders,
    start_here_body,
)
from app.obsidian.application.vault.vault_reindex import VaultReindexExecutor
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianVaultSettingsUpdate,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianReindexResult,
    ObsidianVaultStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.markdown.paths import resolve_note_path
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfig,
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.types.extra_types import JSONValue


class StartHereFrontmatterDict(TypedDict, closed=True):
    """Known two-field frontmatter written by the default START_HERE note."""

    kind: str
    scope: str


# protocol-contract: structural-seam
class ObsidianLifecycleReadHook(Protocol):
    """Read one note by vault-relative path."""

    async def __call__(self, relative_path: str) -> ObsidianNote:
        """Read one note.

        Args:
            relative_path: Vault-relative note path.

        Returns:
            Canonical indexed note.
        """


# protocol-contract: structural-seam
class ObsidianLifecycleSaveHook(Protocol):
    """Persist one note through the canonical save path."""

    async def __call__(self, payload: ObsidianSaveNote) -> ObsidianNote:
        """Save one note.

        Args:
            payload: Canonical save command.

        Returns:
            Persisted and indexed note.
        """


# protocol-contract: structural-seam
class ObsidianMarkSupersededHook(Protocol):
    """Reconcile a superseded Context during reindex."""

    async def __call__(
        self,
        superseded_context_id: str,
        replacement_context_id: str,
    ) -> None:
        """Mark one Context as superseded.

        Args:
            superseded_context_id: Context being replaced.
            replacement_context_id: Canonical replacement Context.
        """


class ObsidianVaultLifecycleService:
    """Own vault settings, bootstrap, and serialized index-rebuild admission."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_config_store: ObsidianVaultConfigStore,
        save_note: ObsidianLifecycleSaveHook,
        read_note_by_path: ObsidianLifecycleReadHook,
        note_id_from_existing_file: Callable[[Path], str | None],
        mark_context_superseded: ObsidianMarkSupersededHook,
        context_reindex_hook: Callable[[Sequence[str] | None], Awaitable[None]] | None,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        embedding_fingerprint_key: str | None = None,
    ) -> None:
        """Create the vault lifecycle service without starting I/O.

        Args:
            repository: Rebuildable PostgreSQL index repository.
            vault_config_store: Runtime vault location provider.
            save_note: Canonical note save callback.
            read_note_by_path: Canonical note read callback.
            note_id_from_existing_file: Safe frontmatter identifier reader.
            mark_context_superseded: Context lifecycle reconciliation callback.
            context_reindex_hook: Optional Context RAG reindex callback.
            index_maintenance_coordinator: Coordinator for the vault reindex lease.
            embedding_fingerprint_key: Active native compile embedding identity.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._save_note = save_note
        self._read_note_by_path = read_note_by_path
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._reindex_executor = VaultReindexExecutor(
            repository=repository,
            vault_config_store=vault_config_store,
            note_id_from_existing_file=note_id_from_existing_file,
            mark_context_superseded=mark_context_superseded,
            context_reindex_hook=context_reindex_hook,
            embedding_fingerprint_key=embedding_fingerprint_key,
            root_path=_root_path,
        )

    async def status(self) -> ObsidianVaultStatus:
        """Return local Obsidian vault and index status.

        Returns:
            Current vault and index status.
        """
        config = self._vault_config_store.current()
        indexed, stale, errors = await self._repository.count_by_status()
        index_errors = await self._repository.list_index_errors()
        root = _root_path(config)
        return ObsidianVaultStatus(
            vault_path=str(config.vault_path),
            alexandria_root=config.alexandria_root,
            vault_exists=config.vault_path.exists(),
            alexandria_root_exists=root.exists(),
            indexed_notes=indexed,
            stale_notes=stale,
            error_notes=errors,
            index_errors=tuple(index_errors),
        )

    async def configure(
        self,
        payload: ObsidianVaultSettingsUpdate,
    ) -> ObsidianVaultStatus:
        """Change the runtime Obsidian vault destination.

        Args:
            payload: Vault settings update request.

        Returns:
            Current vault and index status after applying settings.
        """
        config = self._vault_config_store.normalized(
            vault_path=payload.vault_path,
            alexandria_root=payload.alexandria_root,
        )
        if payload.initialize:
            _ensure_vault_layout(config)
        self._vault_config_store.save(config)
        if payload.initialize:
            await self.initialize()
        if payload.reindex:
            await self.reindex()
        return await self.status()

    async def initialize(self) -> ObsidianNote:
        """Create the managed Obsidian folder layout and START_HERE note.

        Returns:
            The canonical START_HERE note.
        """
        config = self._vault_config_store.current()
        _ensure_vault_layout(config)
        start_path = f"{config.alexandria_root}/START_HERE.md"
        absolute = resolve_note_path(config.vault_path, start_path)
        if not absolute.exists():
            return await self._save_note(
                ObsidianSaveNote(
                    note_id="alexandria_start_here",
                    title="Alexandria START HERE",
                    body=start_here_body(),
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    relative_path=start_path,
                    tags=("alexandria", "start-here"),
                    status="active",
                    source="heterarchy-alexandria",
                    frontmatter=dict[str, JSONValue](
                        **StartHereFrontmatterDict(
                            kind="project_context",
                            scope="global",
                        )
                    ),
                )
            )
        await self.reindex()
        return await self._read_note_by_path(start_path)

    async def reindex(self) -> ObsidianReindexResult:
        """Scan managed Markdown notes and rebuild changed index rows.

        Returns:
            Reindex summary with counts and warnings.
        """
        async with self._index_maintenance_coordinator.operation("vault_reindex"):
            return await self._reindex_executor.run()


def _root_path(config: ObsidianVaultConfig) -> Path:
    """Resolve the configured managed root inside its vault.

    Args:
        config: Typed configuration used by this operation.

    Returns:
        Managed root path inside the configured vault.
    """
    return resolve_note_path(config.vault_path, config.alexandria_root)


def _ensure_vault_layout(config: ObsidianVaultConfig) -> None:
    """Create the default managed folder layout inside the configured vault.

    Args:
        config: Typed configuration used by this operation.
    """
    for folder in default_folders(config.alexandria_root):
        resolve_note_path(config.vault_path, folder).mkdir(parents=True, exist_ok=True)
