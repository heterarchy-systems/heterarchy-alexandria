"""Application-level dependency-injector container."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

from dependency_injector import containers, providers
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections.containers import ConnectionsContainer
from app.librarian.containers import LibrarianContainer
from app.memory.containers import MemoryContainer
from app.memory.domain.repositories.context_graph_signal_provider import (
    IContextGraphSignalProvider,
)
from app.obsidian.application.graph.obsidian_graph_context_signal_service import (
    ObsidianGraphContextSignalService,
)
from app.obsidian.containers import ObsidianContainer
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.infrastructure.graph.neo4j_graph_projection_factory import (
    optional_neo4j_graph_projection_repository,
)
from app.operations.application.external_api_rate_limit import (
    ExternalApiRateLimiter,
    NoopExternalApiRateLimiter,
    RedisExternalApiRateLimiter,
)
from app.operations.application.maintenance_job_queue import MaintenanceJobSubmitter
from app.operations.application.operational_readiness_cache import (
    NoopOperationalReadinessCache,
    OperationalReadinessCache,
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
async def initialize_database(*, database_url: str) -> AsyncGenerator[Database]:
    """Provision Database with startup/shutdown lifecycle.

    Args:
        database_url [str]: Async SQLAlchemy database URL used to create the resource.

    Yields:
        Database: Initialized database resource for the application lifecycle.
    """
    database = Database(database_url=database_url)
    await database.initialize()
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
    *,
    config: AppConfig,
    repository: IObsidianGraphProjectionRepository | None,
) -> IContextGraphSignalProvider | None:
    """Create optional Context graph evidence provider only when enabled.

    Args:
        config: Typed service configuration.
        repository: Enabled graph projection repository, or None while disabled.

    Returns:
        Optional graph signal provider for Context recall enrichment.
    """
    if config.graph_read_model == "disabled" or repository is None:
        return None
    return ObsidianGraphContextSignalService(repository=repository)


class ApplicationContainer(containers.DeclarativeContainer):
    """Root container for shared application resources."""

    wiring_config = containers.WiringConfiguration(
        packages=[
            "app.connections.interface.routers",
            "app.librarian.interface.routers",
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
    graph_projection_repository = providers.Resource(
        optional_neo4j_graph_projection_repository,
        config=app_config,
    )
    graph_signal_provider = providers.Factory(
        create_graph_signal_provider,
        config=app_config,
        repository=graph_projection_repository,
    )

    connections = providers.Container(
        ConnectionsContainer,
        db_session=db_session,
        secret_cipher=secret_cipher,
    )
    memory = providers.Container(
        MemoryContainer,
        db_session=db_session,
        app_config=app_config,
        librarian_provider_repo=connections.librarian_provider_repo,
        provider_secret_repo=connections.provider_secret_repo,
        graph_signal_provider=graph_signal_provider,
        index_maintenance_coordinator=index_maintenance_coordinator,
        external_api_rate_limiter=external_api_rate_limiter,
    )
    librarian = providers.Container(
        LibrarianContainer,
        db_session=db_session,
        librarian_provider_repo=connections.librarian_provider_repo,
        provider_secret_repo=connections.provider_secret_repo,
        external_api_rate_limiter=external_api_rate_limiter,
    )
    obsidian = providers.Container(
        ObsidianContainer,
        db_session=db_session,
        database=database,
        app_config=app_config,
        librarian_delegate_service=librarian.hermes_collaboration_service,
        memory_context_service=memory.context_service,
        memory_embedding_recovery_service=memory.context_embedding_recovery_service,
        graph_projection_repository=graph_projection_repository,
        index_maintenance_coordinator=index_maintenance_coordinator,
    )
