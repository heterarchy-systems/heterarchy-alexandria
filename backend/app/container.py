"""Application-level dependency-injector container."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

from dependency_injector import containers, providers
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.application.contexts.graph.context_graph_candidate_expansion_service import (
    ContextGraphCandidateExpansionService,
    GraphProjectionSnapshotSource,
)
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.integration.context_projection_integrity_service import (
    ContextProjectionIntegrityService,
)
from app.memory.application.reconciliation.cycles.memory_cycle_service import (
    MemoryCycleService,
)
from app.memory.application.reconciliation.cycles.memory_cycle_source_fence import (
    MemoryCycleSourceFence,
)
from app.memory.application.reconciliation.runtime.memory_reconciliation_readiness_service import (
    MemoryReconciliationReadinessService,
)
from app.memory.application.retrieval.obsidian_exact_selector_resolver import (
    ObsidianExactSelectorResolver,
)
from app.memory.application.retrieval.recall_service import RecallService
from app.memory.containers import MemoryContainer
from app.memory.domain.repositories.contexts.graph.context_graph_candidate_expansion_provider import (
    IContextGraphCandidateExpansionProvider,
)
from app.memory.domain.repositories.contexts.graph.context_graph_signal_provider import (
    IContextGraphSignalProvider,
)
from app.memory.infrastructure.repositories.contexts.obsidian.obsidian_graph_candidate_hydrator import (
    ObsidianGraphCandidateHydrator,
)
from app.obsidian.application.graph.projection.obsidian_graph_context_signal_service import (
    ObsidianGraphContextSignalService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.containers import ObsidianContainer
from app.obsidian.domain.repositories.obsidian_graph_candidate_selection_compute_provider import (
    IObsidianGraphCandidateSelectionComputeProvider,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.infrastructure.graph.native_obsidian_graph_candidate_selection_compute_provider import (
    create_native_obsidian_graph_candidate_selection_compute_provider,
)
from app.obsidian.infrastructure.graph.native_obsidian_graph_projection_compute_provider import (
    create_native_obsidian_graph_projection_compute_provider,
)
from app.obsidian.infrastructure.graph.postgresql_obsidian_graph_projection_repository import (
    PostgreSqlObsidianGraphProjectionRepository,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.operations.application.diagnostics.operational_retrieval_diagnostics_service import (
    OperationalRetrievalDiagnosticsService,
)
from app.operations.application.maintenance_job_queue import MaintenanceJobSubmitter
from app.operations.application.readiness.external_api_rate_limit import (
    ExternalApiRateLimiter,
    NoopExternalApiRateLimiter,
    RedisExternalApiRateLimiter,
)
from app.operations.application.readiness.operational_readiness_cache import (
    NoopOperationalReadinessCache,
    OperationalReadinessCache,
)
from app.operations.application.readiness.operational_readiness_service import (
    GraphProjectionReadinessPort,
    OperationalReadinessService,
)
from app.operations.application.readiness.operational_retrieval_canary_service import (
    OperationalRetrievalCanaryService,
)
from app.operations.application.readiness.operational_runtime_provenance_service import (
    OperationalRuntimeProvenanceService,
)
from app.operations.infrastructure.redis_maintenance_job_queue import (
    RedisMaintenanceJobSubmitter,
)
from app.operations.infrastructure.redis_operational_readiness_cache import (
    RedisOperationalReadinessCache,
    RedisReadinessClient,
)
from app.platform.config.app_config import AppConfig
from app.platform.config.database_config import DatabaseConfig
from app.platform.config.maintenance_queue_config import MaintenanceQueueConfig
from app.platform.config.redis_config import RedisConfig
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.infrastructure.database import Database
from app.shared.infrastructure.postgres_advisory_lock import PostgresAdvisoryLock
from app.shared.infrastructure.redis_client import initialize_redis_client
from app.shared.security.secret_cipher import SecretCipher, SecretCipherSettings


@asynccontextmanager
async def initialize_database(database_url: str) -> AsyncGenerator[Database]:
    """Provision the database engine with startup/shutdown lifecycle.

    Application lifecycle health probes own connectivity checks. Constructing
    the engine must not make canonical source reads depend on PostgreSQL uptime.

    Args:
        database_url [str]: Async SQLAlchemy database URL used to create the resource.

        database_url: Database url used by this operation.
    Yields:
        Database: Initialized database resource for the application lifecycle.
    """
    database = Database(database_url=database_url)
    try:
        yield database
    finally:
        await database.shutdown()


def create_operational_readiness_cache(
    config: RedisConfig,
    client: Redis | None,
) -> OperationalReadinessCache:
    """Create an optional Redis readiness cache with a no-op fallback.

    Args:
        config: Validated optional Redis settings.
        client: Shared process-wide Redis client, or None when disabled.

    Returns:
        Redis-backed or disabled operational-readiness cache.
    """
    if config.url is None or client is None:
        return NoopOperationalReadinessCache()
    return RedisOperationalReadinessCache(
        client=cast(RedisReadinessClient, client),
        ttl_seconds=config.operational_readiness_ttl_seconds,
    )


def create_maintenance_job_submitter(
    client: Redis | None,
    config: MaintenanceQueueConfig,
) -> MaintenanceJobSubmitter | None:
    """Create the shared API-facing maintenance queue adapter.

    Args:
        client: Shared process-wide Redis client, or None when Redis is disabled.
        config: Validated Redis Streams maintenance queue settings.

    Returns:
        Redis-backed job submitter when the queue is enabled; otherwise None.
    """
    if client is None or config.redis_url is None:
        return None
    return RedisMaintenanceJobSubmitter(client, config)


def create_external_api_rate_limiter(
    config: RedisConfig,
    client: Redis | None,
) -> ExternalApiRateLimiter:
    """Create a process-scoped provider budget over the shared Redis pool.

    Args:
        config: Validated Redis rate-limit settings.
        client: Shared process-wide Redis client, or None when Redis is disabled.

    Returns:
        Redis-backed external API limiter or the explicit no-op fallback.
    """
    if config.url is None or client is None:
        return NoopExternalApiRateLimiter()
    return RedisExternalApiRateLimiter(
        client,
        config.external_api_rate_limit,
        config.external_api_rate_window_seconds,
    )


def create_session(database: Database) -> AsyncSession:
    """Create a request-local async SQLAlchemy session from Database.

    Args:
        database [Database]: Value supplied to create_session.

        database: Database used by this operation.
    Returns:
        AsyncSession: Value produced by create_session.
    """
    return database.session()


def create_index_maintenance_coordinator(
    database: Database,
) -> IndexMaintenanceCoordinator:
    """Create one process and cross-process index write coordinator.

    Args:
        database: Initialized PostgreSQL database resource.

    Returns:
        Coordinator bound to the database-specific advisory lock when applicable.
    """
    return IndexMaintenanceCoordinator(
        process_lock=PostgresAdvisoryLock(
            database.engine,
            namespace="heterarchy-alexandria:index-maintenance",
        ),
        allow_concurrent_writes=True,
    )


def create_secret_cipher(config: AppConfig) -> SecretCipher:
    """Create the provider secret cipher from typed service settings.

    Args:
        config: Typed service configuration.

    Returns:
        SecretCipher: Configured credential cipher.
    """
    settings = SecretCipherSettings(
        app_name=config.app_name,
        app_env=config.app_env,
        secret_encryption_key=config.secret_encryption_key,
    )
    cipher = SecretCipher.from_settings(settings)
    return cipher


def create_graph_signal_provider(
    repository: IObsidianGraphProjectionRepository,
) -> IContextGraphSignalProvider:
    """Create Context graph evidence over the active PostgreSQL/Rust projection."""
    return ObsidianGraphContextSignalService(repository=repository)


def create_graph_candidate_expansion_provider(
    repository: GraphProjectionSnapshotSource,
    selector: IObsidianGraphCandidateSelectionComputeProvider,
    session: AsyncSession,
) -> IContextGraphCandidateExpansionProvider:
    """Create the measured AUTO-only multi-hop graph expansion provider."""
    return ContextGraphCandidateExpansionService(
        projection_source=repository,
        selector=selector,
        hydrator=ObsidianGraphCandidateHydrator(session),
    )


def create_operational_readiness_service(
    config: AppConfig,
    database: Database,
    context_service: ContextService,
    obsidian_service: ObsidianService,
    reconciliation_service: MemoryReconciliationReadinessService | None,
    readiness_cache: OperationalReadinessCache,
    projection_integrity_service: ContextProjectionIntegrityService,
    runtime_provenance_service: OperationalRuntimeProvenanceService,
    graph_projection_service: GraphProjectionReadinessPort,
) -> OperationalReadinessService:
    """Assemble one request-scoped operational readiness object graph.

    Args:
        config: Validated application configuration.
        database: Shared database lifecycle coordinator.
        context_service: Request-scoped Context application service.
        obsidian_service: Request-scoped canonical Vault application service.
        reconciliation_service: Optional memory reconciliation diagnostics service.
        readiness_cache: Bounded fail-open readiness cache.
        projection_integrity_service: Persisted projection-integrity reader.
        runtime_provenance_service: Application-scoped immutable provenance probe.
        graph_projection_service: Canonical PostgreSQL graph status reader.

    Returns:
        Request-scoped readiness service sharing one Context service with its canary.
    """
    retrieval_canary_service = OperationalRetrievalCanaryService(
        context_service=context_service,
        query=config.readiness_canary_query,
        limit=config.readiness_canary_limit,
    )
    return OperationalReadinessService(
        database=database,
        context_service=context_service,
        obsidian_service=obsidian_service,
        reconciliation_service=reconciliation_service,
        readiness_cache=readiness_cache,
        runtime_provenance_service=runtime_provenance_service,
        retrieval_canary_service=retrieval_canary_service,
        projection_integrity_service=projection_integrity_service,
        graph_projection_service=graph_projection_service,
    )


class ApplicationContainer(containers.DeclarativeContainer):
    """Root container for shared application resources."""

    wiring_config = containers.WiringConfiguration(
        packages=[
            "app.connections.interface.routers",
            "app.memory.interface.routers",
            "app.obsidian.interface.routers",
            "app.operations.interface.routers",
        ],
    )

    app_config = providers.Singleton(AppConfig)
    secret_cipher = providers.Singleton(create_secret_cipher, config=app_config)
    database_config = providers.Singleton(DatabaseConfig)
    redis_config = providers.Singleton(RedisConfig)
    maintenance_queue_config = providers.Singleton(MaintenanceQueueConfig)
    database = providers.Resource(
        initialize_database,
        database_url=database_config.provided.url,
    )
    redis_client = providers.Resource(
        initialize_redis_client,
        config=redis_config,
    )
    operational_readiness_cache = providers.Factory(
        create_operational_readiness_cache,
        config=redis_config,
        client=redis_client,
    )
    maintenance_job_submitter = providers.Resource(
        create_maintenance_job_submitter,
        client=redis_client,
        config=maintenance_queue_config,
    )
    external_api_rate_limiter = providers.Resource(
        create_external_api_rate_limiter,
        config=redis_config,
        client=redis_client,
    )
    db_session = providers.Factory(create_session, database=database)
    index_maintenance_coordinator = providers.Resource(
        create_index_maintenance_coordinator,
        database=database,
    )
    graph_projection_compute_provider = providers.Singleton(
        create_native_obsidian_graph_projection_compute_provider
    )
    graph_projection_repository = providers.Singleton(
        PostgreSqlObsidianGraphProjectionRepository,
        database=database,
        compute_provider=graph_projection_compute_provider,
    )
    graph_signal_provider = providers.Factory(
        create_graph_signal_provider,
        repository=graph_projection_repository,
    )
    graph_candidate_selection_compute_provider = providers.Singleton(
        create_native_obsidian_graph_candidate_selection_compute_provider
    )
    graph_candidate_expansion_provider = providers.Factory(
        create_graph_candidate_expansion_provider,
        repository=graph_projection_repository,
        selector=graph_candidate_selection_compute_provider,
        session=db_session,
    )
    memory = providers.Container(
        MemoryContainer,
        db_session=db_session,
        app_config=app_config,
        graph_signal_provider=graph_signal_provider,
        graph_candidate_expansion_provider=graph_candidate_expansion_provider,
        index_maintenance_coordinator=index_maintenance_coordinator,
        external_api_rate_limiter=external_api_rate_limiter,
    )
    obsidian = providers.Container(
        ObsidianContainer,
        db_session=db_session,
        database=database,
        app_config=app_config,
        memory_context_service=memory.context_service,
        memory_embedding_recovery_service=memory.context_embedding_recovery_service,
        graph_projection_repository=graph_projection_repository,
        index_maintenance_coordinator=index_maintenance_coordinator,
    )
    operational_retrieval_diagnostics_service = providers.Factory(
        OperationalRetrievalDiagnosticsService,
        context_service=memory.context_service,
    )
    recall_exact_selector_resolver = providers.Factory(
        ObsidianExactSelectorResolver,
        obsidian_service=obsidian.obsidian_service,
        canonical_identity_service=obsidian.canonical_identity_service,
    )
    recall_service = providers.Factory(
        RecallService,
        context_service=memory.context_service,
        temporal_recall_service=memory.memory_temporal_recall_service,
        exact_selector_resolver=recall_exact_selector_resolver,
    )
    memory_cycle_source_fence = providers.Factory(
        MemoryCycleSourceFence,
        source=obsidian.obsidian_service,
        context_reader=memory.context_service,
    )
    memory_cycle_service = providers.Factory(
        MemoryCycleService,
        existing_reconciliation_service=memory.memory_existing_reconciliation_service,
        context_service=memory.context_service,
        source_fence=memory_cycle_source_fence,
        reconciliation_repository=memory.reconciliation_repo,
        reconciliation_apply_service=memory.reconciliation_apply_service,
        compact_service=memory.memory_compact_service,
        compact_policy=memory.memory_compact_reconciliation_policy,
        index_maintenance_coordinator=index_maintenance_coordinator,
        checkpoint_store=providers.Factory(
            ObsidianReportBundleRunStore,
            vault_path=obsidian.vault_config_store.provided.current.call().vault_path,
        ),
        commit_projection=db_session.provided.commit,
        rollback_projection=db_session.provided.rollback,
    )
    operational_runtime_provenance_service = providers.Singleton(
        OperationalRuntimeProvenanceService,
        config=app_config,
    )
    operational_readiness_service = providers.Factory(
        create_operational_readiness_service,
        config=app_config,
        database=database,
        context_service=memory.context_service,
        obsidian_service=obsidian.obsidian_service,
        reconciliation_service=memory.memory_reconciliation_readiness_service,
        readiness_cache=operational_readiness_cache,
        projection_integrity_service=obsidian.context_projection_integrity_service,
        runtime_provenance_service=operational_runtime_provenance_service,
        graph_projection_service=obsidian.graph_projection_rebuild_service,
    )
