"""Memory and lifecycle contracts for the Redis maintenance worker."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime
from typing import cast

import anyio
import pytest
from dependency_injector import providers
from tests.config_test_data import (
    maintenance_configuration as maintenance_configuration,
)

import app.operations.workers.redis_maintenance_worker as worker_module
from app.container import ApplicationContainer
from app.operations.application.maintenance_job_queue import (
    MaintenanceJobDelivery,
    MaintenanceJobNotAdmitted,
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
from app.platform.config.redis_config import MaintenanceQueueConfig
from app.shared.infrastructure.database import Database

pytestmark = pytest.mark.usefixtures("maintenance_configuration")


@pytest.fixture(autouse=True)
def _restore_app_wiring_after_worker_test() -> Iterator[None]:
    """Re-wire the default FastAPI container if app.main was already imported."""
    try:
        yield
    finally:
        if "app.main" in sys.modules:
            from app.main import app

            app.state.container.wire()


class _RecordingWorkerClient:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def ping(self) -> bool:
        self._events.append("redis-ping")
        return True

    async def aclose(self) -> None:
        self._events.append("redis-close")


def test_worker_container_defers_unrelated_process_resources() -> None:
    """Worker construction must not eagerly allocate unrelated API or graph resources."""
    config = MaintenanceQueueConfig(_env_file=None).model_copy(
        update={"embedding_threads": 1}
    )
    container = _create_worker_container(config)

    assert container.embedding_config().rag_embedding_threads == 1
    assert container.memory.graph_signal_provider() is None
    assert container.database.initialized is False
    assert container.redis_client.initialized is False
    assert isinstance(container.graph_projection_repository, providers.Singleton)


@pytest.mark.parametrize("exit_mode", ["signal", "cancellation"])
def test_disabled_worker_waits_without_starting_resources(
    exit_mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled worker owns stop signals but creates no queue or app resources."""
    calls: list[str] = []
    signal_installed = asyncio.Event()
    stop_events: list[asyncio.Event] = []
    install_signal_handlers = worker_module._install_signal_handlers

    def record_signal_install(stop_event: asyncio.Event) -> None:
        install_signal_handlers(stop_event)
        stop_events.append(stop_event)
        signal_installed.set()

    def fail_if_called(name: str) -> object:
        calls.append(name)
        raise AssertionError(f"disabled worker created {name}")

    monkeypatch.setenv("SERVICE_REDIS_MAINTENANCE_QUEUE_ENABLED", "false")
    monkeypatch.setenv("SERVICE_REDIS_URL", "redis://cache:6379/0")
    monkeypatch.setattr(
        worker_module, "_install_signal_handlers", record_signal_install
    )
    monkeypatch.setattr(
        worker_module,
        "create_maintenance_worker_client",
        lambda _config: fail_if_called("Redis client"),
    )
    monkeypatch.setattr(
        worker_module,
        "RedisMaintenanceJobSubmitter",
        lambda _client, _config: fail_if_called("submitter"),
    )
    monkeypatch.setattr(
        worker_module,
        "RedisMaintenanceJobConsumer",
        lambda _client, _config, _submitter: fail_if_called("consumer"),
    )
    monkeypatch.setattr(
        worker_module,
        "_create_worker_container",
        lambda _config: fail_if_called("application container"),
    )

    async def scenario() -> None:
        task = asyncio.create_task(run_worker())
        await asyncio.wait_for(signal_installed.wait(), timeout=1)
        assert len(stop_events) == 1
        assert not task.done()

        if exit_mode == "signal":
            stop_events[0].set()
            await task
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    anyio.run(scenario)
    assert calls == []


def test_enabled_worker_starts_and_closes_its_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled startup retains its consumer path and closes client and DB resources."""

    async def scenario() -> tuple[list[str], ApplicationContainer | None]:
        events: list[str] = []
        loop_started = asyncio.Event()
        stop_events: list[asyncio.Event] = []
        client = _RecordingWorkerClient(events)
        container: ApplicationContainer | None = None
        create_container = worker_module._create_worker_container
        install_signal_handlers = worker_module._install_signal_handlers

        async def database_resource() -> AsyncGenerator[Database]:
            events.append("database-open")
            yield cast(Database, object())
            events.append("database-close")

        def create_test_container(
            config: MaintenanceQueueConfig,
        ) -> ApplicationContainer:
            nonlocal container
            container = create_container(config)
            container.database.override(providers.Resource(database_resource))
            return container

        def record_signal_install(stop_event: asyncio.Event) -> None:
            install_signal_handlers(stop_event)
            stop_events.append(stop_event)

        class RecordingSubmitter:
            def __init__(
                self,
                current_client: object,
                config: MaintenanceQueueConfig,
            ) -> None:
                del current_client, config
                events.append("submitter-created")

        class RecordingConsumer:
            async def ensure_consumer_group(self) -> None:
                events.append("consumer-group-ready")

        async def wait_for_stop(
            worker_index: int,
            stop_event: asyncio.Event,
            consumer: RedisMaintenanceJobConsumer,
            database: Database,
            current_container: ApplicationContainer,
        ) -> None:
            del worker_index, consumer, database, current_container
            events.append("consumer-started")
            loop_started.set()
            await stop_event.wait()
            events.append("consumer-stopped")

        monkeypatch.setenv("SERVICE_REDIS_MAINTENANCE_QUEUE_ENABLED", "true")
        monkeypatch.setenv("SERVICE_REDIS_MAINTENANCE_WORKER_CONCURRENCY", "1")
        monkeypatch.setenv("SERVICE_REDIS_URL", "redis://cache:6379/0")
        monkeypatch.setattr(
            worker_module,
            "create_maintenance_worker_client",
            lambda _config: client,
        )
        monkeypatch.setattr(
            worker_module,
            "RedisMaintenanceJobSubmitter",
            RecordingSubmitter,
        )
        monkeypatch.setattr(
            worker_module,
            "RedisMaintenanceJobConsumer",
            lambda _client, _config, _submitter: RecordingConsumer(),
        )
        monkeypatch.setattr(
            worker_module,
            "_create_worker_container",
            create_test_container,
        )
        monkeypatch.setattr(
            worker_module, "_install_signal_handlers", record_signal_install
        )
        monkeypatch.setattr(worker_module, "_consumer_loop", wait_for_stop)

        task = asyncio.create_task(run_worker())
        await asyncio.wait_for(loop_started.wait(), timeout=1)
        assert len(stop_events) == 1
        stop_events[0].set()
        await task
        return events, container

    events, container = anyio.run(scenario)

    assert container is not None
    assert events == [
        "submitter-created",
        "database-open",
        "redis-ping",
        "consumer-group-ready",
        "consumer-started",
        "consumer-stopped",
        "redis-close",
        "database-close",
    ]


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


def test_worker_does_not_execute_when_atomic_admission_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reclaim rejection never crosses the effect boundary."""

    async def scenario() -> bool:
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

        class RejectedAdmissionConsumer:
            async def mark_running(
                self,
                current_delivery: MaintenanceJobDelivery,
            ) -> MaintenanceJobNotAdmitted:
                del current_delivery
                return MaintenanceJobNotAdmitted()

        executed = False

        async def execute_job(
            current_delivery: MaintenanceJobDelivery,
            database: Database,
            container: ApplicationContainer,
        ) -> object:
            nonlocal executed
            del current_delivery, database, container
            executed = True
            raise AssertionError("rejected work crossed the effect boundary")

        monkeypatch.setattr(worker_module, "_execute_job", execute_job)
        await worker_module._process_delivery(
            delivery,
            cast(RedisMaintenanceJobConsumer, RejectedAdmissionConsumer()),
            cast(Database, object()),
            cast(ApplicationContainer, object()),
        )
        return executed

    assert anyio.run(scenario) is False
