"""Dependency-injector container for Obsidian bounded context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.application.contexts.embedding.context_embedding_recovery_service import (
    ContextEmbeddingRecoveryService,
)
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.integration.context_projection_integrity_service import (
    ContextProjectionIntegrityService,
)
from app.memory.infrastructure.repositories.projection_integrity.projection_integrity_store import (
    ContextProjectionIntegrityStore,
)
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
from app.obsidian.infrastructure.graph.native_obsidian_graph_projection_compute_provider import (
    create_native_obsidian_graph_projection_compute_provider,
)
from app.obsidian.infrastructure.graph.sqlalchemy_obsidian_graph_projection_source import (
    SqlAlchemyObsidianGraphProjectionSource,
)
from app.obsidian.infrastructure.markdown.native_context_reindex_manifest import (
    create_native_context_reindex_manifest_validator,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.platform.config.app_config import AppConfig
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.infrastructure.database import Database


def _build_context_reindex_hook(
    enabled: bool,
    context_service: ContextService | None,
    recovery_service: ContextEmbeddingRecoveryService | None,
    projection_integrity_service: ContextProjectionIntegrityService,
) -> Callable[[], Awaitable[None]] | None:
    """Build an async hook that backfills context embeddings after vault reindex.

    Args:
        enabled: Whether the capability is enabled.
        context_service: Context service dependency.
        recovery_service: Recovery service dependency.
        projection_integrity_service: Full indexed-note Context projection scanner.

    Returns:
        Constructed context reindex hook.
    """

    async def _hook() -> None:
        """Execute hook."""
        await projection_integrity_service.refresh()
        if enabled and context_service is not None and recovery_service is not None:
            await recovery_service.recover(context_service)

    return _hook


class ObsidianContainer(containers.DeclarativeContainer):
    """Container for Obsidian vault and index services."""

    db_session = providers.Dependency(instance_of=AsyncSession)
    database = providers.Dependency(instance_of=Database)
    app_config = providers.Dependency(instance_of=AppConfig)
    memory_context_service = providers.Dependency(
        instance_of=ContextService,
        default=None,
    )
    memory_embedding_recovery_service = providers.Dependency(
        instance_of=ContextEmbeddingRecoveryService,
        default=None,
    )
    graph_projection_repository = providers.Dependency()
    index_maintenance_coordinator = providers.Dependency(
        instance_of=IndexMaintenanceCoordinator
    )
    index_repo = providers.Factory(
        SqlAlchemyObsidianIndexRepository, session=db_session
    )
    context_projection_integrity_store = providers.Factory(
        ContextProjectionIntegrityStore,
        session=db_session,
    )
    context_projection_integrity_service = providers.Factory(
        ContextProjectionIntegrityService,
        source=index_repo,
        repository=context_projection_integrity_store,
        max_age_seconds=app_config.provided.projection_integrity_max_age_seconds,
    )
    graph_projection_source = providers.Factory(
        SqlAlchemyObsidianGraphProjectionSource,
        session=db_session,
    )
    graph_projection_compute_provider = providers.Singleton(
        create_native_obsidian_graph_projection_compute_provider,
    )
    context_reindex_manifest_validator = providers.Singleton(
        create_native_context_reindex_manifest_validator,
    )
    graph_projection_source_builder = providers.Factory(
        ObsidianGraphProjectionSourceBuilder,
        source=graph_projection_source,
        compute_provider=graph_projection_compute_provider,
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
        context_reindex_manifest_validator=context_reindex_manifest_validator,
        context_reindex_hook=providers.Factory(
            _build_context_reindex_hook,
            enabled=app_config.provided.rag_embedding_recovery_on_vault_reindex,
            context_service=memory_context_service,
            recovery_service=memory_embedding_recovery_service,
            projection_integrity_service=context_projection_integrity_service,
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
