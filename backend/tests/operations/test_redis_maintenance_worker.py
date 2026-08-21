"""Memory and lifecycle contracts for the Redis maintenance worker."""

from __future__ import annotations

from datetime import UTC, datetime
from inspect import getsource
from typing import cast

import anyio
import app.operations.workers.redis_maintenance_worker as worker_module
import pytest
from app.container import ApplicationContainer
from app.operations.application.maintenance_job_queue import (
    MaintenanceJobDelivery,
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import MaintenanceJobSnapshot
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.operations.infrastructure.redis_maintenance_job_consumer import (
    RedisMaintenanceJobConsumer,
)
from app.operations.workers.redis_maintenance_worker import (
    _create_worker_container,
    run_worker,
)
from app.platform.config.maintenance_queue_config import MaintenanceQueueConfig
from app.shared.infrastructure.database import Database


def test_worker_container_defers_unrelated_process_resources() -> None:
    """Worker construction must not eagerly allocate API Redis or Neo4j clients."""
    config = MaintenanceQueueConfig(_env_file=None).model_copy(
        update={"embedding_threads": 1}
    )
    container = _create_worker_container(config)

    assert container.app_config().rag_embedding_threads == 1
    assert container.memory.graph_signal_provider() is None
    assert container.database.initialized is False
    assert container.redis_client.initialized is False
    assert container.graph_projection_repository.initialized is False


def test_worker_startup_does_not_initialize_every_application_resource() -> None:
    """The worker should initialize only resources reached by the reindex path."""
    assert "init_resources" not in getsource(run_worker)


def test_worker_embedding_threads_are_loaded_from_dedicated_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker CPU concurrency should not reuse the API embedding-thread setting."""
    monkeypatch.setenv("SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS", "2")

    config = MaintenanceQueueConfig(_env_file=None)

    assert config.embedding_threads == 2


class _SingleDeliveryConsumer:
    """Return one delivery while worker error handling owns loop termination."""

    def __init__(self, delivery: MaintenanceJobDelivery) -> None:
        self._delivery = delivery

    async def receive(self, consumer_name: str) -> MaintenanceJobDelivery:
        """Return the configured delivery for the current consumer."""
        del consumer_name
        return self._delivery


def test_consumer_loop_survives_delivery_transition_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Redis transition outage must not escape and terminate the TaskGroup."""

    async def scenario() -> bool:
        stop_event = anyio.Event()
        delivery = MaintenanceJobDelivery(
            stream_id="1-0",
            job=MaintenanceJobSnapshot(
                job_id="job-1",
                kind=MaintenanceJobKind.EMBEDDING_REINDEX,
                status=MaintenanceJobStatus.RUNNING,
                requested_by="test",
                source_id="test-source",
                limit=1,
                force=False,
                attempts=1,
                submitted_at=datetime(2026, 8, 20, tzinfo=UTC),
            ),
        )
        consumer = cast(
            RedisMaintenanceJobConsumer,
            _SingleDeliveryConsumer(delivery),
        )

        async def fail_delivery(
            current_delivery: MaintenanceJobDelivery,
            current_consumer: RedisMaintenanceJobConsumer,
            database: Database,
            container: ApplicationContainer,
        ) -> None:
            del current_delivery, current_consumer, database, container
            raise MaintenanceQueueUnavailableError("transition unavailable")

        async def stop_after_failure(
            current_stop_event: anyio.Event,
            seconds: float,
        ) -> None:
            del seconds
            current_stop_event.set()

        monkeypatch.setattr(worker_module, "_process_delivery", fail_delivery)
        monkeypatch.setattr(worker_module, "_interruptible_sleep", stop_after_failure)
        await worker_module._consumer_loop(
            0,
            cast(worker_module.asyncio.Event, stop_event),
            consumer,
            cast(Database, object()),
            cast(ApplicationContainer, object()),
        )
        return stop_event.is_set()

    assert anyio.run(scenario) is True
