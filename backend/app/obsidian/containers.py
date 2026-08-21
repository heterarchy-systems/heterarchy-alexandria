"""Dependency-injector container for Obsidian bounded context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.memory.application.contexts.embedding.context_embedding_recovery_service import (
    ContextEmbeddingRecoveryService,
)
from app.memory.application.contexts.records.context_service import ContextService
from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_service import (
    ObsidianGraphNoteDiagnosticsService,
)
from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_source_builder import (
    ObsidianGraphProjectionSourceBuilder,
)
from app.obsidian.application.librarian.workflow.obsidian_librarian_job_service import (
    ObsidianLibrarianJobService,
)
from app.obsidian.application.librarian.workflow.obsidian_librarian_workflow_service import (
    ObsidianLibrarianWorkflowService,
)
from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.notes.obsidian_report_bundle_service import (
    ObsidianReportBundleService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.application.service.vault.obsidian_vault_reindex_service import (
    ObsidianVaultReindexService,
)
from app.obsidian.infrastructure.graph.sqlalchemy_obsidian_graph_projection_source import (
    SqlAlchemyObsidianGraphProjectionSource,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.obsidian.infrastructure.repositories.obsidian_workflow_repository import (
    SqlAlchemyObsidianWorkflowRepository,
)
from app.platform.config.app_config import AppConfig
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.infrastructure.database import Database
from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession


def _build_context_reindex_hook(
    enabled: bool,
    context_service: ContextService | None,
    recovery_service: ContextEmbeddingRecoveryService | None,
) -> Callable[[], Awaitable[None]] | None:
    """Build an async hook that backfills context embeddings after vault reindex."""
    if not enabled or context_service is None or recovery_service is None:
        return None

    async def _hook() -> None:
        await recovery_service.recover(context_service)

    return _hook


class ObsidianContainer(containers.DeclarativeContainer):
    """Container for Obsidian vault and index services."""

    db_session = providers.Dependency(instance_of=AsyncSession)
    database = providers.Dependency(instance_of=Database)
    app_config = providers.Dependency(instance_of=AppConfig)
    librarian_delegate_service = providers.Dependency(default=None)
    memory_context_service = providers.Dependency(
        instance_of=ContextService,
        default=None,
    )
    memory_embedding_recovery_service = providers.Dependency(
        instance_of=ContextEmbeddingRecoveryService,
        default=None,
    )
    graph_projection_repository = providers.Dependency(default=None)
    index_maintenance_coordinator = providers.Dependency(
        instance_of=IndexMaintenanceCoordinator
    )
    index_repo = providers.Factory(
        SqlAlchemyObsidianIndexRepository, session=db_session
    )
    graph_projection_source = providers.Factory(
        SqlAlchemyObsidianGraphProjectionSource,
        session=db_session,
    )
    graph_projection_source_builder = providers.Factory(
        ObsidianGraphProjectionSourceBuilder,
        source=graph_projection_source,
    )
    graph_projection_rebuild_service = providers.Factory(
        ObsidianGraphProjectionRebuildService,
        config=app_config,
        source_builder=graph_projection_source_builder,
        repository=graph_projection_repository,
        index_maintenance_coordinator=index_maintenance_coordinator,
    )
    vault_config_store = providers.Singleton(
        ObsidianVaultConfigStore,
        default_vault_path=app_config.provided.obsidian_vault_path,
        default_alexandria_root=app_config.provided.alexandria_obsidian_root,
        config_path=app_config.provided.obsidian_vault_config_path,
    )
    graph_note_diagnostics_service = providers.Factory(
        ObsidianGraphNoteDiagnosticsService,
        repository=index_repo,
        source=graph_projection_source,
        projection_service=graph_projection_rebuild_service,
        vault_config_store=vault_config_store,
        index_maintenance_coordinator=index_maintenance_coordinator,
    )
    obsidian_service = providers.Factory(
        ObsidianService,
        repository=index_repo,
        vault_config_store=vault_config_store,
        delegate_service=librarian_delegate_service,
        context_reindex_hook=providers.Factory(
            _build_context_reindex_hook,
            enabled=app_config.provided.rag_embedding_recovery_on_vault_reindex,
            context_service=memory_context_service,
            recovery_service=memory_embedding_recovery_service,
        ),
        index_maintenance_coordinator=index_maintenance_coordinator,
    )
    vault_reindex_service = providers.Factory(
        ObsidianVaultReindexService,
        obsidian_service=obsidian_service,
        graph_projection_rebuild_service=graph_projection_rebuild_service,
    )
    graph_service = providers.Factory(
        ObsidianGraphService,
        repository=index_repo,
        graph_repository=graph_projection_repository,
    )
    report_bundle_service = providers.Factory(
        ObsidianReportBundleService,
        obsidian_service=obsidian_service,
        vault_reindex_service=vault_reindex_service,
        graph_service=graph_service,
        vault_config_store=vault_config_store,
        index_maintenance_coordinator=index_maintenance_coordinator,
    )
    canonical_identity_service = providers.Factory(
        ObsidianCanonicalIdentityService,
        obsidian_service=obsidian_service,
        vault_config_store=vault_config_store,
    )
    job_service = providers.Singleton(
        ObsidianLibrarianJobService,
        database=database,
        vault_config_store=vault_config_store,
        delegate_service=librarian_delegate_service,
    )
    workflow_repo = providers.Factory(
        SqlAlchemyObsidianWorkflowRepository, session=db_session
    )
    workflow_service = providers.Factory(
        ObsidianLibrarianWorkflowService.from_services,
        workflow_repository=workflow_repo,
        obsidian_service=obsidian_service,
        delegate_service=librarian_delegate_service,
    )
