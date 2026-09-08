"""Application service for Obsidian-backed Alexandria notes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from app.obsidian.application.notes.lifecycle.obsidian_context_reindex_manifest import (
    UNCONFIGURED_CONTEXT_REINDEX_MANIFEST_VALIDATOR,
    ContextReindexManifestValidator,
)
from app.obsidian.application.service.notes.obsidian_context_lifecycle_service import (
    ObsidianContextLifecycleService,
)
from app.obsidian.application.service.notes.obsidian_index_error_repair_service import (
    ObsidianIndexErrorRepairService,
)
from app.obsidian.application.service.notes.obsidian_legacy_metadata_repair_service import (
    ObsidianLegacyMetadataRepairService,
)
from app.obsidian.application.service.notes.obsidian_note_service import (
    DEFAULT_SOURCE_SCAN_LIMIT,
    ObsidianNoteService,
)
from app.obsidian.application.service.obsidian_service_ports import (
    ObsidianMutationPort,
    ObsidianRecoveryPort,
)
from app.obsidian.application.service.vault.obsidian_vault_inventory_service import (
    ObsidianVaultInventoryService,
)
from app.obsidian.application.service.vault.obsidian_vault_lifecycle_service import (
    ObsidianVaultLifecycleService,
)
from app.obsidian.application.service.vault.obsidian_vault_move_service import (
    ObsidianVaultMoveService,
)
from app.obsidian.application.service.vault.obsidian_vault_operations import (
    ObsidianVaultOperations,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianSearchQuery,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianNoteWriteResult,
    ObsidianSearchHit,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianValidationError,
)


class ObsidianService(
    ObsidianVaultOperations, ObsidianRecoveryPort, ObsidianMutationPort
):
    """Expose the stable Obsidian application facade.

    Focused inventory and vault-move responsibilities are delegated to
    collaborators while this facade preserves the existing router contract.
    """

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_path: str | None = None,
        alexandria_root: str = "Alexandria",
        vault_config_store: ObsidianVaultConfigStore | None = None,
        context_reindex_hook: Callable[[], Awaitable[None]] | None = None,
        index_maintenance_coordinator: IndexMaintenanceCoordinator | None = None,
        context_reindex_manifest_validator: ContextReindexManifestValidator = (
            UNCONFIGURED_CONTEXT_REINDEX_MANIFEST_VALIDATOR
        ),
    ) -> None:
        """Initialize service dependencies.

        Args:
            repository: Rebuildable PostgreSQL index repository.
            vault_path: Obsidian vault root.
            alexandria_root: Managed folder inside the vault.
            vault_config_store: Optional runtime vault override store.
            context_reindex_hook: Callback invoked for context reindex.
            index_maintenance_coordinator: Index maintenance coordinator used by this operation.
            context_reindex_manifest_validator: Cross-note manifest validation authority.
        """
        self._repository = repository
        if vault_config_store is None:
            if vault_path is None:
                raise ObsidianValidationError("vault_path is required")
            vault_config_store = ObsidianVaultConfigStore(
                default_vault_path=vault_path,
                default_alexandria_root=alexandria_root,
                config_path=None,
            )
        self._vault_config_store = vault_config_store
        self._index_maintenance_coordinator = (
            index_maintenance_coordinator or IndexMaintenanceCoordinator()
        )
        self._context_lifecycle_service = ObsidianContextLifecycleService(
            repository=self._repository,
            vault_config_store=self._vault_config_store,
            read_note=self.read_note,
        )
        self._vault_lifecycle_service = ObsidianVaultLifecycleService(
            repository=self._repository,
            context_reindex_manifest_validator=context_reindex_manifest_validator,
            vault_config_store=self._vault_config_store,
            save_note=self.save_note,
            read_note_by_path=self.read_note_by_path,
            note_id_from_existing_file=self._note_id_from_existing_file,
            mark_context_superseded=self._delegate_mark_context_superseded,
            context_reindex_hook=context_reindex_hook,
            index_maintenance_coordinator=self._index_maintenance_coordinator,
        )
        self._index_error_repair_service = ObsidianIndexErrorRepairService(
            repository=self._repository,
            vault_config_store=self._vault_config_store,
            reindex=self.reindex,
            status=self.status,
        )
        self._legacy_metadata_repair_service = ObsidianLegacyMetadataRepairService(
            vault_config_store=self._vault_config_store,
            reindex=self.reindex,
        )
        self._vault_inventory_service = ObsidianVaultInventoryService(
            vault_config_store=self._vault_config_store
        )
        self._note_service = ObsidianNoteService(
            repository=self._repository,
            vault_config_store=self._vault_config_store,
            reindex=self.reindex,
            mark_context_superseded=self._delegate_mark_context_superseded,
            index_maintenance_coordinator=self._index_maintenance_coordinator,
            source_snapshot=self._vault_inventory_service.source_snapshot,
            source_scan_limit=DEFAULT_SOURCE_SCAN_LIMIT,
        )
        self._vault_move_service = ObsidianVaultMoveService(
            vault_config_store=self._vault_config_store,
            reindex=self.reindex,
            search=self.search,
        )

    async def search(
        self,
        query: ObsidianSearchQuery,
        refresh: bool = False,
    ) -> list[ObsidianSearchHit]:
        """Search Obsidian notes through the PostgreSQL index.

        Args:
            query: Search filters and query text.
            refresh: Whether to re-scan the vault before querying.

        Returns:
            Ranked search hits.
        """
        return await self._note_service.search(query, refresh=refresh)

    async def read_note(self, note_id: str) -> ObsidianNote:
        """Read one managed note by stable id.

        Args:
            note_id: Stable note id from frontmatter.

        Returns:
            Authoritative note loaded from Markdown.
        """
        return await self._note_service.read_note(note_id)

    async def read_note_by_path(self, relative_path: str) -> ObsidianNote:
        """Read one managed note by vault-relative path.

        Args:
            relative_path: Vault-relative Markdown path.

        Returns:
            Authoritative note loaded from Markdown.
        """
        return await self._note_service.read_note_by_path(relative_path)

    async def save_note(self, payload: ObsidianSaveNote) -> ObsidianNote:
        """Create or replace one Alexandria-managed Markdown note.

        Args:
            payload: Save request with body and metadata.

        Returns:
            Saved note loaded through the index.
        """
        return await self._note_service.save_note(payload)

    async def write_note(
        self,
        command: ObsidianWriteNote,
    ) -> ObsidianNoteWriteResult:
        """Execute explicit create, update, or upsert semantics.

        Args:
            command: Value supplied to write_note.

        Returns:
            Result produced by write_note.
        """
        return await self._note_service.write_note(command)

    async def archive_context(self, note_id: str) -> ObsidianNote:
        """Archive one canonical Context while preserving its Markdown content.

        Args:
            note_id: Canonical Obsidian note identifier.

        Returns:
            Reindexed archived Context note.
        """
        return await self._context_lifecycle_service.archive(note_id)

    async def supersede_context(
        self,
        note_id: str,
        replacement_note_id: str,
    ) -> tuple[ObsidianNote, ObsidianNote]:
        """Link an existing canonical Context to an existing replacement.

        Args:
            note_id: Canonical Context identifier to supersede.
            replacement_note_id: Canonical replacement Context identifier.

        Returns:
            Superseded and replacement canonical notes.
        """
        return await self._context_lifecycle_service.supersede(
            note_id,
            replacement_note_id,
        )

    async def _delegate_mark_context_superseded(
        self,
        superseded_context_id: str,
        replacement_context_id: str,
    ) -> None:
        """Execute delegate mark context superseded.

        Args:
            superseded_context_id: Identifier for superseded context.
            replacement_context_id: Identifier for replacement context.
        """
        await self._mark_context_superseded(
            superseded_context_id=superseded_context_id,
            replacement_context_id=replacement_context_id,
        )

    async def _mark_context_superseded(
        self,
        superseded_context_id: str,
        replacement_context_id: str,
    ) -> None:
        """Execute mark context superseded.

        Args:
            superseded_context_id: Identifier for superseded context.
            replacement_context_id: Identifier for replacement context.
        """
        await self._context_lifecycle_service.mark_superseded(
            superseded_context_id=superseded_context_id,
            replacement_context_id=replacement_context_id,
        )

    def _note_id_from_existing_file(self, path: Path) -> str | None:
        """Execute note id from existing file.

        Args:
            path: Path used by this operation.

        Returns:
            str | None result produced by note id from existing file.
        """
        return self._note_service.note_id_from_existing_file(path)
