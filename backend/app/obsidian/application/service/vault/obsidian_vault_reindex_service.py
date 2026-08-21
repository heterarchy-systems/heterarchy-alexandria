"""Composite Obsidian vault and optional graph projection reindex service."""

from __future__ import annotations

from dataclasses import dataclass

from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildReport,
    ObsidianGraphProjectionRebuildService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.entities.obsidian_note import ObsidianReindexResult


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultReindexReport:
    """Composite report for public Obsidian reindex orchestration."""

    vault_index: ObsidianReindexResult
    graph_projection: ObsidianGraphProjectionRebuildReport


class ObsidianVaultReindexService:
    """Coordinate canonical Markdown indexing before graph projection rebuilds."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        graph_projection_rebuild_service: ObsidianGraphProjectionRebuildService,
    ) -> None:
        """Create the public reindex orchestrator.

        Args:
            obsidian_service: Canonical Markdown to PostgreSQL reindex service.
            graph_projection_rebuild_service: Optional graph projection rebuild service.
        """
        self._obsidian_service = obsidian_service
        self._graph_projection_rebuild_service = graph_projection_rebuild_service

    async def rebuild(self) -> ObsidianVaultReindexReport:
        """Rebuild the PostgreSQL index first, then rebuild the optional graph projection.

        The underlying services each own their maintenance lease. Calling them
        sequentially here ensures the graph projection reads the fresh PostgreSQL index
        source after the vault reindex lock has been released.

        Returns:
            Combined vault-index and graph-projection rebuild report.
        """
        vault_index = await self._obsidian_service.reindex()
        graph_projection = await self._graph_projection_rebuild_service.rebuild()
        return ObsidianVaultReindexReport(
            vault_index=vault_index,
            graph_projection=graph_projection,
        )
