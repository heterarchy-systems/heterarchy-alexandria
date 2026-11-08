"""Durable, idempotent high-level relation orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_service import (
    ObsidianGraphNoteDiagnosticsService,
)
from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.notes.relations.apply import RelationApplyCoordinator
from app.obsidian.application.notes.relations.checkpoints import open_store
from app.obsidian.application.notes.relations.contracts import (
    normalize_request,
    relate_request_hash,
    validate_request,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_relation_contracts import (
    ObsidianRelateRequest,
)
from app.obsidian.domain.entities.obsidian_relation import ObsidianRelateResult
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)


class ObsidianRelateService:
    """Coordinate canonical Markdown, indexed edges, graph projection and replay."""

    def __init__(
        self,
        *,
        obsidian_service: ObsidianService,
        graph_note_diagnostics_service: ObsidianGraphNoteDiagnosticsService,
        graph_service: ObsidianGraphService,
        graph_repository: IObsidianGraphProjectionRepository,
        vault_config_store: ObsidianVaultConfigStore,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        commit_projection: Callable[[], Awaitable[None]],
        rollback_projection: Callable[[], Awaitable[None]],
    ) -> None:
        """Create a request-scoped relation orchestration owner.

        Args:
            obsidian_service: Canonical note read and mutation boundary.
            graph_note_diagnostics_service: Existing graph rebuild owner.
            graph_service: Existing directed relation read owner.
            graph_repository: Existing active projection read authority.
            vault_config_store: Existing current-vault configuration owner.
            index_maintenance_coordinator: Shared index operation serializer.
            commit_projection: Existing SQLAlchemy projection commit callback.
            rollback_projection: Existing SQLAlchemy projection rollback callback.
        """
        self._vault_config_store = vault_config_store
        self._apply_coordinator = RelationApplyCoordinator(
            obsidian_service=obsidian_service,
            graph_note_diagnostics_service=graph_note_diagnostics_service,
            graph_service=graph_service,
            graph_repository=graph_repository,
            index_maintenance_coordinator=index_maintenance_coordinator,
            commit_projection=commit_projection,
            rollback_projection=rollback_projection,
        )

    async def relate(self, request: ObsidianRelateRequest) -> ObsidianRelateResult:
        """Relate two existing notes with durable idempotency and graph readback.

        Args:
            request: Caller-provided relation intent.

        Returns:
            Relation outcome with canonical-source and graph verification evidence.
        """
        request = normalize_request(request)
        validate_request(request)
        request_hash = relate_request_hash(request)
        checkpoint_key = f"relate:{request.idempotency_key}"
        store = open_store(self._vault_config_store)
        return await self._apply_coordinator.apply(
            request=request,
            request_hash=request_hash,
            checkpoint_key=checkpoint_key,
            store=store,
        )
