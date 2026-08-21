"""Stable vault-facing operations shared by the Obsidian application facade.

This class owns only API delegation. Canonical Markdown mutation, indexing, repair,
inventory, and move rules remain in their focused application services.
"""

from __future__ import annotations

from pathlib import Path

from app.obsidian.application.service.librarian.obsidian_librarian_review_service import (
    ObsidianLibrarianReviewService,
)
from app.obsidian.application.service.notes.obsidian_index_error_repair_service import (
    ObsidianIndexErrorRepairService,
)
from app.obsidian.application.service.notes.obsidian_legacy_metadata_repair_service import (
    ObsidianLegacyMetadataRepairService,
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
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianReviewApplyRequest,
    ObsidianLibrarianReviewQueueRequest,
    ObsidianVaultInventoryRequest,
    ObsidianVaultMoveApplyRequest,
    ObsidianVaultMovePlanRequest,
    ObsidianVaultSettingsUpdate,
)
from app.obsidian.domain.entities.obsidian_index_error_repair import (
    ObsidianIndexErrorRepairPlan,
    ObsidianIndexErrorRepairReport,
)
from app.obsidian.domain.entities.obsidian_legacy_metadata_repair import (
    ObsidianLegacyMetadataRepairPlan,
    ObsidianLegacyMetadataRepairReport,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianLibrarianReviewQueueItem,
    ObsidianNote,
    ObsidianReindexResult,
    ObsidianVaultInventoryItem,
    ObsidianVaultLocation,
    ObsidianVaultMovePlan,
    ObsidianVaultMoveReport,
    ObsidianVaultStatus,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)


class ObsidianVaultOperations:
    """Expose the stable vault/repair/curation facade over focused services."""

    _index_error_repair_service: ObsidianIndexErrorRepairService
    _legacy_metadata_repair_service: ObsidianLegacyMetadataRepairService
    _librarian_review_service: ObsidianLibrarianReviewService
    _vault_config_store: ObsidianVaultConfigStore
    _vault_inventory_service: ObsidianVaultInventoryService
    _vault_lifecycle_service: ObsidianVaultLifecycleService
    _vault_move_service: ObsidianVaultMoveService

    @property
    def _vault_path(self) -> Path:
        return self._vault_config_store.current().vault_path

    @property
    def _alexandria_root(self) -> str:
        return self._vault_config_store.current().alexandria_root

    def vault_location(self) -> ObsidianVaultLocation:
        """Return the canonical Vault path without reading the PostgreSQL index.

        Returns:
            Vault and managed-root location used by source-preserving backups.
        """
        config = self._vault_config_store.current()
        return ObsidianVaultLocation(
            vault_path=str(config.vault_path),
            alexandria_root=config.alexandria_root,
        )

    async def status(self) -> ObsidianVaultStatus:
        """Return local Obsidian vault and index status.

        Returns:
            Current vault and index status.
        """
        return await self._vault_lifecycle_service.status()

    async def configure_vault_settings(
        self,
        payload: ObsidianVaultSettingsUpdate,
    ) -> ObsidianVaultStatus:
        """Change the runtime Obsidian vault destination.

        Args:
            payload: Vault settings update request.

        Returns:
            Current vault and index status after applying settings.
        """
        return await self._vault_lifecycle_service.configure(payload)

    async def initialize_vault(self) -> ObsidianNote:
        """Create the managed folder layout and START_HERE note.

        Returns:
            The canonical START_HERE note.
        """
        return await self._vault_lifecycle_service.initialize()

    async def reindex(self) -> ObsidianReindexResult:
        """Scan managed Markdown notes and rebuild changed index rows.

        Returns:
            Reindex summary with counts and warnings.
        """
        return await self._vault_lifecycle_service.reindex()

    async def plan_index_error_repairs(self) -> ObsidianIndexErrorRepairPlan:
        """Build a non-mutating plan for known legacy index errors.

        Returns:
            Hash-locked repair plan.
        """
        return await self._index_error_repair_service.plan()

    async def apply_index_error_repairs(
        self,
        expected_plan_hash: str,
    ) -> ObsidianIndexErrorRepairReport:
        """Apply a hash-locked, backup-first legacy index repair plan.

        Args:
            expected_plan_hash: Plan hash accepted by the operator.

        Returns:
            Applied repair report.
        """
        return await self._index_error_repair_service.apply(
            expected_plan_hash=expected_plan_hash
        )

    async def plan_legacy_metadata_repairs(
        self,
    ) -> ObsidianLegacyMetadataRepairPlan:
        """Scan managed Markdown for repairable legacy metadata.

        Returns:
            Non-mutating metadata repair plan.
        """
        return await self._legacy_metadata_repair_service.plan()

    async def apply_legacy_metadata_repairs(
        self,
        expected_plan_hash: str,
    ) -> ObsidianLegacyMetadataRepairReport:
        """Apply an unchanged, backup-first legacy metadata repair plan.

        Args:
            expected_plan_hash: Hash of the inspected plan accepted for apply.

        Returns:
            Applied repair report with content-hash evidence.
        """
        return await self._legacy_metadata_repair_service.apply(
            expected_plan_hash=expected_plan_hash
        )

    async def inventory_vault(
        self,
        request: ObsidianVaultInventoryRequest,
    ) -> list[ObsidianVaultInventoryItem]:
        """Inventory managed Markdown notes under a vault-relative scope.

        Args:
            request: Inventory request with optional scope path.

        Returns:
            Managed note inventory items sorted by path.
        """
        return await self._vault_inventory_service.inventory(request)

    async def managed_markdown_paths(self) -> list[str]:
        """List every managed Markdown source regardless of index validity.

        Returns:
            Vault-relative managed Markdown paths.
        """
        return await self._vault_inventory_service.managed_markdown_paths()

    async def search_vault_paths(
        self,
        query: str,
        scope_path: str | None = None,
    ) -> list[ObsidianVaultInventoryItem]:
        """Search inventoried paths and note metadata without relying on FTS.

        Args:
            query: Keyword or path fragment to find.
            scope_path: Optional vault-relative scope.

        Returns:
            Matching managed note inventory items.
        """
        return await self._vault_inventory_service.search_paths(
            query=query,
            scope_path=scope_path,
        )

    async def librarian_review_queue(
        self,
        request: ObsidianLibrarianReviewQueueRequest,
    ) -> list[ObsidianLibrarianReviewQueueItem]:
        """List managed notes that need librarian curation.

        Args:
            request: Review queue scope, project, and limit contract.

        Returns:
            Prioritized librarian review candidates.
        """
        return await self._librarian_review_service.review_queue(request)

    async def plan_librarian_review_moves(
        self,
        request: ObsidianLibrarianReviewQueueRequest,
    ) -> ObsidianVaultMovePlan:
        """Build a dry-run move plan from librarian review candidates.

        Args:
            request: Review queue scope, project, and limit contract.

        Returns:
            Safety-validated move plan.
        """
        return await self._librarian_review_service.plan_moves(request)

    async def apply_librarian_review_moves(
        self,
        request: ObsidianLibrarianReviewApplyRequest,
    ) -> ObsidianVaultMoveReport:
        """Apply safe moves generated from librarian review candidates.

        Args:
            request: Review queue and report application contract.

        Returns:
            Applied move report and verification metadata.
        """
        return await self._librarian_review_service.apply_moves(request)

    async def plan_vault_moves(
        self,
        request: ObsidianVaultMovePlanRequest,
    ) -> ObsidianVaultMovePlan:
        """Build a dry-run move plan without mutating the vault.

        Args:
            request: Requested vault moves.

        Returns:
            Safety-validated move plan.
        """
        return await self._vault_move_service.plan(request)

    async def apply_vault_moves(
        self,
        request: ObsidianVaultMoveApplyRequest,
    ) -> ObsidianVaultMoveReport:
        """Safely apply a move plan, reindex, verify, and write reports.

        Args:
            request: Move application and verification contract.

        Returns:
            Applied move report and report paths.
        """
        return await self._vault_move_service.apply(request)
