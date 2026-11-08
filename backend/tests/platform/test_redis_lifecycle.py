"""Optional shared Redis client and cache lifecycle contracts."""

from __future__ import annotations

from typing import ClassVar, cast

import anyio
import pytest
from redis.asyncio import Redis

import app.shared.infrastructure.redis_client as redis_client_module
from app.container import (
    create_external_api_rate_limiter,
    create_maintenance_job_submitter,
    create_operational_readiness_cache,
)
from app.operations.application.readiness.external_api_rate_limit import (
    RedisExternalApiRateLimiter,
)
from app.operations.application.readiness.operational_readiness_cache import (
    NoopOperationalReadinessCache,
)
from app.operations.infrastructure.redis_operational_readiness_cache import (
    RedisOperationalReadinessCache,
)
from app.platform.config.redis_config import MaintenanceQueueConfig
from app.platform.config.redis_config import RedisConfig
from app.shared.infrastructure.redis_client import (
    create_redis_client,
    initialize_redis_client,
)


class _FakeRedisClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _RecordingRedisType:
    client: ClassVar[_FakeRedisClient] = _FakeRedisClient()
    calls: ClassVar[list[tuple[str, bool, float, float, int, int]]] = []

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        decode_responses: bool,
        socket_connect_timeout: float,
        socket_timeout: float,
        health_check_interval: int,
        max_connections: int,
    ) -> _FakeRedisClient:
        cls.calls.append(
            (
                url,
                decode_responses,
                socket_connect_timeout,
                socket_timeout,
                health_check_interval,
                max_connections,
            )
        )
        return cls.client


def test_create_redis_client_uses_bounded_lazy_connection_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared client should remain lazy and cap socket and pool resources."""
    _RecordingRedisType.client = _FakeRedisClient()
    _RecordingRedisType.calls = []
    monkeypatch.setattr(redis_client_module, "Redis", _RecordingRedisType)

    client = create_redis_client("redis://cache:6379/0", max_connections=5)

    assert client is _RecordingRedisType.client
    assert _RecordingRedisType.calls == [
        ("redis://cache:6379/0", False, 0.25, 0.75, 30, 5)
    ]


def test_disabled_redis_resource_yields_none() -> None:
    """Redis remains disabled unless a URL is explicitly configured."""

    async def scenario() -> bool:
        config = RedisConfig(_env_file=None, url=None)
        async with initialize_redis_client(config=config) as client:
            return client is None

    assert anyio.run(scenario) is True


def test_configured_redis_resource_closes_shared_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The process resource should close its bounded client during shutdown."""

    async def scenario() -> tuple[bool, bool]:
        client = _FakeRedisClient()
        monkeypatch.setattr(
            redis_client_module,
            "create_redis_client",
            lambda redis_url, max_connections: client,
        )
        config = RedisConfig(
            _env_file=None,
            url="redis://cache:6379/0",
            max_connections=3,
        )
        async with initialize_redis_client(config=config) as opened:
            was_open_inside = opened is client and not client.closed
        return was_open_inside, client.closed

    assert anyio.run(scenario) == (True, True)


def test_readiness_cache_is_noop_without_enabled_shared_client() -> None:
    """Cache wiring should fail open when Redis is disabled or unavailable."""
    disabled = RedisConfig(_env_file=None, url=None)
    configured = RedisConfig(_env_file=None, url="redis://cache:6379/0")

    assert isinstance(
        create_operational_readiness_cache(disabled, None),
        NoopOperationalReadinessCache,
    )
    assert isinstance(
        create_operational_readiness_cache(configured, None),
        NoopOperationalReadinessCache,
    )


def test_readiness_cache_reuses_the_shared_client() -> None:
    """Enabled cache adapters should not allocate an additional Redis pool."""
    config = RedisConfig(
        _env_file=None,
        url="redis://cache:6379/0",
        operational_readiness_ttl_seconds=3,
    )
    client = cast(Redis, _FakeRedisClient())

    cache = create_operational_readiness_cache(config, client)

    assert isinstance(cache, RedisOperationalReadinessCache)


def test_disabled_maintenance_queue_preserves_shared_redis_adapters() -> None:
    """Disabling maintenance delivery leaves Redis cache and rate limits active."""
    client = cast(Redis, _FakeRedisClient())
    redis_config = RedisConfig(_env_file=None, url="redis://cache:6379/0")
    queue_config = MaintenanceQueueConfig(
        _env_file=None,
        redis_url="redis://cache:6379/0",
        queue_enabled=False,
    )

    assert create_maintenance_job_submitter(client, queue_config) is None
    assert isinstance(
        create_operational_readiness_cache(redis_config, client),
        RedisOperationalReadinessCache,
    )
    assert isinstance(
        create_external_api_rate_limiter(redis_config, client),
        RedisExternalApiRateLimiter,
    )
