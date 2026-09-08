"""Bounded Redis Streams worker for CPU-heavy maintenance operations."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from collections.abc import Awaitable
from typing import cast

from dependency_injector import providers

from app.container import ApplicationContainer
from app.memory.application.contexts.records.context_service import ContextService
from app.operations.application.maintenance_job_queue import (
    MaintenanceJobDelivery,
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import EmbeddingReindexJobResult
from app.operations.domain.event_enum.maintenance_job_enums import MaintenanceJobKind
from app.operations.infrastructure.redis_maintenance_job_consumer import (
    RedisMaintenanceJobConsumer,
)
from app.operations.infrastructure.redis_maintenance_job_queue import (
    RedisMaintenanceJobSubmitter,
    create_maintenance_worker_client,
)
from app.platform.config.app_config import AppConfig
from app.platform.config.maintenance_queue_config import MaintenanceQueueConfig
from app.shared.infrastructure.database import Database

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    """Run bounded consumer loops until the process receives a stop signal."""
    config = MaintenanceQueueConfig()
    client = create_maintenance_worker_client(config)
    submitter = RedisMaintenanceJobSubmitter(client, config)
    consumer = RedisMaintenanceJobConsumer(client, config, submitter)
    container = _create_worker_container(config)
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    try:
        database = await cast(Awaitable[Database], container.database())
        await cast(Awaitable[bool], client.ping())
        await consumer.ensure_consumer_group()
        async with asyncio.TaskGroup() as task_group:
            for worker_index in range(config.worker_concurrency):
                task_group.create_task(
                    _consumer_loop(
                        worker_index,
                        stop_event,
                        consumer,
                        database,
                        container,
                    ),
                    name=f"redis-maintenance-worker-{worker_index}",
                )
            await stop_event.wait()
    finally:
        await client.aclose()
        await cast(Awaitable[None], container.shutdown_resources())


def _create_worker_container(config: MaintenanceQueueConfig) -> ApplicationContainer:
    """Create a lazy worker container without API-only Redis or graph resources.

    Embedding reindexing uses the embedding service and index coordinator, but it
    does not consume graph recall signals. Overriding that dependency prevents a
    graph projection resources from being initialized for embedding-only work. Resource
    initialization stays lazy so the worker does not also allocate the API Redis
    pool or unrelated application resources.

    Args:
        config: Typed configuration used by this operation.

    Returns:
        Created worker container.
    """
    container = ApplicationContainer()
    container.app_config.override(
        providers.Object(
            AppConfig().model_copy(
                update={"rag_embedding_threads": config.embedding_threads}
            ),
        )
    )
    container.graph_signal_provider.override(providers.Object(None))
    container.memory.context_service.enable_async_mode()
    return container


async def _consumer_loop(
    worker_index: int,
    stop_event: asyncio.Event,
    consumer: RedisMaintenanceJobConsumer,
    database: Database,
    container: ApplicationContainer,
) -> None:
    """Execute consumer loop.

    Args:
        worker_index: Worker index used by this operation.
        stop_event: Stop event used by this operation.
        consumer: Consumer used by this operation.
        database: Database used by this operation.
        container: Container used by this operation.
    """
    consumer_name = f"{socket.gethostname()}-{os.getpid()}-{worker_index}"
    while not stop_event.is_set():
        try:
            delivery = await consumer.receive(consumer_name)
        except MaintenanceQueueUnavailableError:
            logger.exception("maintenance queue receive failed")
            await _interruptible_sleep(stop_event, 2.0)
            continue
        if delivery is None:
            continue
        try:
            await _process_delivery(delivery, consumer, database, container)
        except MaintenanceQueueUnavailableError:
            logger.exception("maintenance queue delivery transition failed")
            await _interruptible_sleep(stop_event, 2.0)


async def _process_delivery(
    delivery: MaintenanceJobDelivery,
    consumer: RedisMaintenanceJobConsumer,
    database: Database,
    container: ApplicationContainer,
) -> None:
    """Process delivery.

    Args:
        delivery: Delivery used by this operation.
        consumer: Consumer used by this operation.
        database: Database used by this operation.
        container: Container used by this operation.
    """
    attempt = await consumer.mark_running(delivery)
    try:
        result = await _execute_job(delivery, database, container)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error_summary = _safe_error_summary(exc)
        logger.error(
            "maintenance job execution failed",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={
                "job_id": delivery.job.job_id,
                "kind": delivery.job.kind.value,
                "attempt": attempt,
                "error_summary": error_summary,
            },
        )
        terminal = await consumer.mark_failed(
            delivery,
            attempt,
            error_summary,
        )
        logger.warning(
            "maintenance job failure transition persisted",
            extra={
                "job_id": delivery.job.job_id,
                "kind": delivery.job.kind.value,
                "attempt": attempt,
                "terminal": terminal,
            },
        )
        return
    await consumer.mark_succeeded(delivery, result)
    logger.info(
        "maintenance job succeeded",
        extra={
            "job_id": delivery.job.job_id,
            "kind": delivery.job.kind.value,
            "attempt": attempt,
            "scanned": result.scanned,
            "updated": result.updated,
            "skipped": result.skipped,
        },
    )


async def _execute_job(
    delivery: MaintenanceJobDelivery,
    database: Database,
    container: ApplicationContainer,
) -> EmbeddingReindexJobResult:
    """Execute job.

    Args:
        delivery: Delivery used by this operation.
        database: Database used by this operation.
        container: Container used by this operation.

    Returns:
        EmbeddingReindexJobResult result produced by execute job.
    """
    if delivery.job.kind is not MaintenanceJobKind.EMBEDDING_REINDEX:
        raise RuntimeError(f"unsupported maintenance job kind: {delivery.job.kind}")
    async with database.request_session():
        service = await cast(
            Awaitable[ContextService],
            container.memory.context_service(),
        )
        result = await service.reindex_embeddings(
            limit=delivery.job.limit,
            force=delivery.job.force,
        )
    return EmbeddingReindexJobResult(
        scanned=result.scanned,
        updated=result.updated,
        skipped=result.skipped,
        warnings=tuple(result.warnings),
    )


def _safe_error_summary(exc: Exception) -> str:
    """Execute safe error summary.

    Args:
        exc: Exception raised by the underlying operation.

    Returns:
        str result produced by safe error summary.
    """
    message = " ".join(str(exc).split())
    if message:
        return f"{type(exc).__name__}: {message}"[:1000]
    return type(exc).__name__


async def _interruptible_sleep(stop_event: asyncio.Event, seconds: float) -> None:
    """Execute interruptible sleep.

    Args:
        stop_event: Stop event used by this operation.
        seconds: Seconds used by this operation.
    """
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Execute install signal handlers.

    Args:
        stop_event: Stop event used by this operation.
    """
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signal_name, stop_event.set)
        except NotImplementedError:
            signal.signal(
                signal_name,
                lambda _signum, _frame: stop_event.set(),
            )


def main() -> None:
    """CLI-compatible synchronous worker entrypoint."""
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
