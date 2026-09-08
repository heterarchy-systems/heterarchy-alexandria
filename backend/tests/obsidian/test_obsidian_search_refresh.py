"""Obsidian search refresh behavior contracts."""

from __future__ import annotations

import anyio

from app.obsidian.application.service.notes.obsidian_note_service import (
    DEFAULT_SOURCE_SCAN_LIMIT,
    ObsidianNoteService,
)
from app.obsidian.application.service.vault.obsidian_vault_inventory_service import (
    ObsidianVaultInventoryService,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSearchQuery
from app.obsidian.domain.entities.obsidian_note import ObsidianReindexResult
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)


class _SearchRepository:
    def __init__(self) -> None:
        self.search_calls = 0

    async def search(self, query: ObsidianSearchQuery) -> list[object]:
        del query
        self.search_calls += 1
        return []


def test_search_uses_existing_index_unless_refresh_is_explicit(tmp_path) -> None:
    """Ordinary search must not turn into a full vault scan by default."""
    repository = _SearchRepository()
    reindex_calls = 0

    async def reindex() -> ObsidianReindexResult:
        nonlocal reindex_calls
        reindex_calls += 1
        return ObsidianReindexResult(
            files_seen=0,
            files_indexed=0,
            files_skipped=0,
            stale_marked=0,
        )

    async def mark_context_superseded(**_: str) -> None:
        return None

    vault_config_store = ObsidianVaultConfigStore(
        default_vault_path=str(tmp_path / "vault"),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    service = ObsidianNoteService(
        repository=repository,
        vault_config_store=vault_config_store,
        reindex=reindex,
        mark_context_superseded=mark_context_superseded,
        index_maintenance_coordinator=IndexMaintenanceCoordinator(),
        source_snapshot=ObsidianVaultInventoryService(
            vault_config_store
        ).source_snapshot,
        source_scan_limit=DEFAULT_SOURCE_SCAN_LIMIT,
    )

    async def scenario() -> None:
        query = ObsidianSearchQuery(query="graph")
        await service.search(query)
        await service.search(query, refresh=True)

    anyio.run(scenario)

    assert reindex_calls == 1
    assert repository.search_calls == 2
