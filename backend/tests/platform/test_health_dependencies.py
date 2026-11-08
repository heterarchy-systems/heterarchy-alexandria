"""Readiness reflects the configured shared Redis resource and its lifecycle."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import pytest
from dependency_injector import providers
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.config_test_data import application_container

import app.shared.infrastructure.redis_client as redis_client_module
from app.main import create_app
from app.platform.config.redis_config import RedisConfig
from app.platform.lifecycle.dependency_health_enums import DependencyHealthStatus
from app.shared.infrastructure.database import Database


class _RedisProbe:
    def __init__(self, outcome: bool | BaseException) -> None:
        self.outcome = outcome
        self.closed = False
        self.ready_at_close: bool | None = None
        self.is_ready: Callable[[], bool] = lambda: False

    async def ping(self) -> bool:
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    async def aclose(self) -> None:
        self.ready_at_close = self.is_ready()
        self.closed = True


@pytest.fixture
def redis_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore_default_app_wiring: None,
) -> tuple[FastAPI, _RedisProbe]:
    probe = _RedisProbe(True)
    monkeypatch.setattr(
        redis_client_module, "create_redis_client", lambda *_args: probe
    )
    application = create_app(
        application_container(
            rag_embedding_recovery_on_startup=False,
            obsidian_vault_path=str(tmp_path / "vault"),
            obsidian_vault_config_path=str(tmp_path / "vault-config.json"),
        )
    )
    application.state.container.redis_config.override(
        providers.Object(RedisConfig(_env_file=None, url="redis://test-redis:6379/0"))
    )
    probe.is_ready = lambda: application.state.lifecycle.snapshot().ready
    return application, probe


@pytest.mark.parametrize(
    ("outcome", "expected_status", "expected_redis"),
    [
        (True, 200, "ok"),
        (False, 503, "unavailable"),
        (RedisConnectionError("offline"), 503, "unavailable"),
        (TimeoutError("deadline"), 503, "unavailable"),
    ],
)
def test_configured_redis_is_probed_at_startup_and_on_health_requests(
    redis_app: tuple[FastAPI, _RedisProbe],
    outcome: bool | BaseException,
    expected_status: int,
    expected_redis: str,
) -> None:
    application, probe = redis_app
    probe.outcome = outcome
    with TestClient(application) as client:
        assert (
            application.state.lifecycle.snapshot().redis_status.value == expected_redis
        )
        ready = client.get("/health/ready")
        assert ready.status_code == expected_status
        assert ready.json()["checks"]["redis"] == expected_redis
        assert ready.json()["reason"] == (
            None if expected_status == 200 else "redis_unavailable"
        )
        heartbeat = client.get("/health/heartbeat")
        assert heartbeat.status_code == expected_status
        assert heartbeat.json()["heartbeat"]["redis"] == expected_redis
    assert probe.closed


def test_readiness_recovers_after_redis_returns(
    redis_app: tuple[FastAPI, _RedisProbe],
) -> None:
    application, probe = redis_app
    with TestClient(application) as client:
        probe.outcome = RedisConnectionError("offline")
        assert client.get("/health/ready").status_code == 503
        probe.outcome = True
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["checks"]["redis"] == "ok"
        application.state.lifecycle.start_draining("test drain")
        assert client.get("/health/ready").status_code == 503
        assert (
            application.state.lifecycle.snapshot().redis_status
            is DependencyHealthStatus.DRAINING
        )


def test_shutdown_stops_readiness_before_closing_redis(
    redis_app: tuple[FastAPI, _RedisProbe],
) -> None:
    application, probe = redis_app
    with TestClient(application):
        assert application.state.lifecycle.snapshot().ready
    assert probe.closed
    assert probe.ready_at_close is False


def test_reentered_lifespan_refreshes_dependencies_before_yield(
    redis_app: tuple[FastAPI, _RedisProbe],
) -> None:
    application, _probe = redis_app
    for _ in range(2):
        with TestClient(application):
            snapshot = application.state.lifecycle.snapshot()
            assert snapshot.ready
            assert snapshot.redis_status is DependencyHealthStatus.OK


def test_failed_startup_closes_initialized_resources(
    redis_app: tuple[FastAPI, _RedisProbe], monkeypatch: pytest.MonkeyPatch
) -> None:
    application, probe = redis_app

    async def broken_ping(_database: Database) -> bool:
        raise RuntimeError("startup probe failed")

    monkeypatch.setattr(Database, "ping", broken_ping)
    with (
        pytest.raises(RuntimeError, match="startup probe failed"),
        TestClient(application),
    ):
        pass
    assert probe.closed
    assert not application.state.lifecycle.snapshot().ready


def test_redis_probe_cancellation_propagates_and_closes_resources(
    redis_app: tuple[FastAPI, _RedisProbe],
) -> None:
    application, probe = redis_app
    probe.outcome = asyncio.CancelledError()

    async def scenario() -> None:
        with pytest.raises(asyncio.CancelledError):
            async with application.router.lifespan_context(application):
                pass

    anyio.run(scenario)
    assert probe.closed
    assert not application.state.lifecycle.snapshot().ready


def test_shutdown_preserves_caller_cancellation_during_recovery_cleanup(
    redis_app: tuple[FastAPI, _RedisProbe], monkeypatch: pytest.MonkeyPatch
) -> None:
    application, probe = redis_app
    application = create_app(
        application_container(
            **application.state.container.vault_config().model_dump(),
            rag_embedding_recovery_on_startup=True,
        )
    )
    application.state.container.redis_config.override(
        providers.Object(RedisConfig(_env_file=None, url="redis://test-redis:6379/0"))
    )
    original_session = Database.request_session

    async def scenario() -> None:
        recovery_started = asyncio.Event()
        recovery_cleaning = asyncio.Event()
        lifespan_started = asyncio.Event()
        begin_shutdown = asyncio.Event()
        never = asyncio.Event()

        @asynccontextmanager
        async def waiting_session(database: Database) -> AsyncIterator[AsyncSession]:
            async with original_session(database) as session:
                recovery_started.set()
                try:
                    await never.wait()
                except asyncio.CancelledError:
                    recovery_cleaning.set()
                    await never.wait()
                    raise
                yield session

        monkeypatch.setattr(Database, "request_session", waiting_session)

        async def run_lifespan() -> None:
            async with application.router.lifespan_context(application):
                await recovery_started.wait()
                lifespan_started.set()
                await begin_shutdown.wait()

        owner = asyncio.create_task(run_lifespan())
        try:
            async with asyncio.timeout(5):
                await lifespan_started.wait()
                begin_shutdown.set()
                await recovery_cleaning.wait()
                owner.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await owner
        finally:
            if not owner.done():
                owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)

    anyio.run(scenario)
    assert probe.closed
    assert not application.state.lifecycle.snapshot().ready
