"""Backend application entrypoint for heterarchy-alexandria."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager, suppress
from typing import cast

from dependency_injector import providers
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.exc import SQLAlchemyError

from app.connections.interface.routers.connection_hub_router import (
    router as connection_hub_router,
)
from app.container import ApplicationContainer
from app.mcp_server.backend_api_client import AlexandriaApiClient, AlexandriaApiSettings
from app.mcp_server.http_auth_factory import build_mcp_http_auth_gate
from app.mcp_server.http_mount import (
    MCP_HTTP_MOUNT_PATH,
    McpHttpMount,
    mcp_streamable_http_lifespan,
)
from app.mcp_server.interface.routers.protected_resource_metadata_router import (
    router as protected_resource_metadata_router,
)
from app.mcp_server.local_oauth.runtime import build_local_mcp_oauth_runtime
from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.memory.application.contexts.embedding.context_embedding_recovery_service import (
    ContextEmbeddingRecoveryService,
)
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.interface.routers.context_retrieval_router import (
    router as context_retrieval_router,
)
from app.memory.interface.routers.context_router import router as context_router
from app.memory.interface.routers.memory_compact_router import (
    router as memory_compact_router,
)
from app.memory.interface.routers.memory_existing_reconciliation_router import (
    router as memory_existing_reconciliation_router,
)
from app.memory.interface.routers.memory_reconciliation_router import (
    router as memory_reconciliation_router,
)
from app.obsidian.interface.routers.obsidian_router import router as obsidian_router
from app.obsidian.interface.routers.obsidian_settings_router import (
    router as obsidian_settings_router,
)
from app.operations.interface.routers.maintenance_job_router import (
    router as maintenance_job_router,
)
from app.operations.interface.routers.operational_readiness_router import (
    router as operational_readiness_router,
)
from app.operations.interface.routers.recovery_plan_router import (
    router as recovery_plan_router,
)
from app.operations.interface.routers.recovery_run_router import (
    router as recovery_run_router,
)
from app.operations.interface.routers.retrieval_diagnostics_router import (
    router as retrieval_diagnostics_router,
)
from app.platform.config.app_config import AppConfig
from app.platform.config.redis_config import RedisConfig
from app.platform.health_router import install_health_routes
from app.platform.lifecycle.dependency_health_enums import PlatformDependency
from app.platform.lifecycle.state import LifecycleState
from app.platform.logging.formatter.config import configure_logging
from app.platform.middleware.database_session import install_database_session_middleware
from app.platform.middleware.public_surface_access import (
    install_public_surface_access_middleware,
)
from app.platform.middleware.redis_status_cache import (
    install_redis_status_cache_middleware,
)
from app.platform.middleware.request_logging import install_request_logging_middleware
from app.shared.infrastructure.database import Database
from app.shared.security.secret_cipher import SecretCipher

logger = logging.getLogger(__name__)


async def _recover_embeddings_after_startup(
    container: ApplicationContainer,
    database: Database,
) -> None:
    """Run bounded embedding recovery in an isolated database request scope.

    Args:
        container: Container used by this operation.
        database: Database used by this operation.
    """
    try:
        async with database.request_session():
            context_service = await cast(
                Awaitable[ContextService],
                container.memory.context_service(),
            )
            recovery_service = cast(
                ContextEmbeddingRecoveryService,
                container.memory.context_embedding_recovery_service(),
            )
            result = await recovery_service.recover(context_service)
        logger.info(
            "startup embedding recovery completed",
            extra={
                "event": "startup_embedding_recovery_completed",
                "attributes": {
                    "scanned": result.scanned,
                    "updated": result.updated,
                    "skipped": result.skipped,
                    "warnings": list(result.warnings),
                },
            },
        )
    except (OSError, RuntimeError, SQLAlchemyError):
        logger.exception(
            "startup embedding recovery failed",
            extra={"event": "startup_embedding_recovery_failed"},
        )


def _docs_urls(app_env: str) -> tuple[str | None, str | None, str | None]:
    """Return docs endpoint paths based on the current environment.

    Args:
        app_env: Current app environment.

    Returns:
        Tuple for docs URL, redoc URL, and OpenAPI URL.
    """
    if app_env == "local":
        return "/docs", "/redoc", "/openapi.json"
    return None, None, None


def create_app(app_config: AppConfig) -> FastAPI:
    """Build the FastAPI application and wire core runtime dependencies.

    Args:
        app_config: Application configuration values.

    Returns:
        Configured FastAPI app.
    """
    lifecycle = LifecycleState()
    container = ApplicationContainer()
    container.app_config.override(providers.Object(app_config))
    container.memory.context_service.enable_async_mode()
    mcp_mount = McpHttpMount(build_mcp_http_auth_gate(app_config))
    mcp_api_settings = AlexandriaApiSettings.from_env()
    mcp_api_client = AlexandriaApiClient(mcp_api_settings)

    async def refresh_dependency_health() -> None:
        """Refresh dependency health before serving readiness requests.

        Args:
            None.

        Returns:
            None.
        """
        database = await cast(Awaitable[Database], container.database())
        if await database.ping():
            lifecycle.dependencies.mark_healthy(PlatformDependency.DATABASE)
        else:
            lifecycle.dependencies.mark_unavailable(PlatformDependency.DATABASE)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Start and stop shared application resources.

        Args:
            _app: Active FastAPI app instance.

        Yields:
            Values yielded by lifespan.

        Returns:
            Async lifecycle context.
        """
        configure_logging()
        await cast(Awaitable[None], container.init_resources())
        database = await cast(Awaitable[Database], container.database())
        local_oauth_runtime = None
        if app_config.mcp_auth_mode is McpAuthMode.LOCAL_OAUTH2:
            secret_cipher = cast(SecretCipher, container.secret_cipher())
            local_oauth_runtime = build_local_mcp_oauth_runtime(
                config=app_config,
                database=database,
                secret_cipher=secret_cipher,
            )
        app.state.local_mcp_oauth_provider = (
            None if local_oauth_runtime is None else local_oauth_runtime.provider
        )
        embedding_recovery_task: asyncio.Task[None] | None = None
        if app_config.rag_embedding_recovery_on_startup:
            embedding_recovery_task = asyncio.create_task(
                _recover_embeddings_after_startup(
                    container=container,
                    database=database,
                ),
                name="alexandria-startup-embedding-recovery",
            )
        lifecycle.dependencies.mark_starting(PlatformDependency.DATABASE)
        if await database.ping():
            lifecycle.dependencies.mark_healthy(PlatformDependency.DATABASE)
        else:
            lifecycle.dependencies.mark_unavailable(PlatformDependency.DATABASE)
        lifecycle.mark_running()
        try:
            async with mcp_streamable_http_lifespan(
                client=mcp_api_client,
                transport_host=app_config.mcp_transport_host,
                local_oauth_runtime=local_oauth_runtime,
            ) as mcp_app:
                mcp_mount.set_app(mcp_app)
                try:
                    yield
                finally:
                    mcp_mount.set_app(None)
        finally:
            app.state.local_mcp_oauth_provider = None
            if (
                embedding_recovery_task is not None
                and not embedding_recovery_task.done()
            ):
                embedding_recovery_task.cancel()
            if embedding_recovery_task is not None:
                with suppress(asyncio.CancelledError):
                    await embedding_recovery_task
            await cast(Awaitable[None], container.shutdown_resources())
            lifecycle.mark_stopping()

    docs_url, redoc_url, openapi_url = _docs_urls(app_config.app_env)
    app = FastAPI(
        title="heterarchy-alexandria API",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        version=app_config.app_version,
    )

    app.state.lifecycle = lifecycle
    app.state.container = container
    app.state.app_config = app_config
    app.state.local_mcp_oauth_provider = None

    async def resolve_database() -> Database:
        """Resolve the lifecycle-owned database resource for request middleware.

        Returns:
            Active application database resource.
        """
        database = await cast(Awaitable[Database], container.database())
        return database

    async def resolve_redis_client() -> Redis | None:
        """Resolve the lifecycle-owned shared Redis client for middleware.

        Returns:
            Initialized shared Redis client, or None while Redis is disabled.
        """
        client = await cast(Awaitable[Redis | None], container.redis_client())
        return client

    container.wire(
        packages=[
            "app.connections.interface.routers",
            "app.memory.interface.routers",
            "app.obsidian.interface.routers",
            "app.operations.interface.routers",
        ]
    )

    install_database_session_middleware(app, resolve_database=resolve_database)
    install_redis_status_cache_middleware(
        app,
        cast(RedisConfig, container.redis_config()),
        resolve_redis_client,
    )
    install_public_surface_access_middleware(app)
    install_request_logging_middleware(app, logger=logger)
    install_health_routes(
        app,
        lifecycle=lifecycle,
        refresh_dependency_health=refresh_dependency_health,
    )
    app.include_router(protected_resource_metadata_router)
    app.include_router(connection_hub_router)
    app.include_router(context_router)
    app.include_router(context_retrieval_router)
    app.include_router(memory_compact_router)
    app.include_router(memory_existing_reconciliation_router)
    app.include_router(memory_reconciliation_router)
    app.include_router(obsidian_router)
    app.include_router(obsidian_settings_router)
    app.include_router(operational_readiness_router)
    app.include_router(retrieval_diagnostics_router)
    app.include_router(recovery_plan_router)
    app.include_router(recovery_run_router)
    app.include_router(maintenance_job_router)

    @app.get("/")
    def root() -> dict[str, str]:
        """Return service metadata for quick readiness checks.

        Args:
            None.

        Returns:
            Service metadata object.
        """
        return {
            "service": app_config.app_name,
            "version": app_config.app_version,
            "status": "ok",
        }

    app.mount(MCP_HTTP_MOUNT_PATH, mcp_mount)
    return app


app = create_app(AppConfig())


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
