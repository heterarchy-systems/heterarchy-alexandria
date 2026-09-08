"""Redis operational readiness cache contracts."""

from __future__ import annotations

from typing import cast

import anyio
import pytest
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService

from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)
from app.operations.infrastructure.redis_operational_readiness_cache import (
    DEFAULT_READINESS_CACHE_KEY,
    RedisOperationalReadinessCache,
)
from app.shared.infrastructure.database import Database


class _HealthyPostgresSession:
    async def __aenter__(self) -> _HealthyPostgresSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        if str(statement) != "SELECT 1":
            raise AssertionError(f"Unexpected SQL: {statement}")

    async def scalar(self, statement: object) -> str | int | None:
        rendered = str(statement)
        if rendered == "SELECT 1":
            return 1
        if "to_regclass" in rendered:
            return "alembic_version"
        if rendered == "SELECT version_num FROM alembic_version":
            return "202608062130_pg_search"
        raise AssertionError(f"Unexpected SQL: {rendered}")


class _HealthyPostgresDatabase:
    dialect_name = "postgresql"

    def session_factory(self):
        return _HealthyPostgresSession


class _HealthyContextService:
    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.HEALTHY,
            embedding=RagHealthState.HEALTHY,
            default_strategy=RagStrategy.HYBRID,
            model_name="test-model",
            dimensions=3,
            fingerprint={"provider": "test"},
            warnings=(),
        )


class _HealthyObsidianService:
    async def status(self) -> ObsidianVaultStatus:
        return ObsidianVaultStatus(
            vault_path="vault",
            alexandria_root="Alexandria",
            vault_exists=True,
            alexandria_root_exists=True,
            indexed_notes=3,
            stale_notes=0,
            error_notes=0,
            index_errors=(),
        )


class _FakeRedisClient:
    def __init__(self) -> None:
        self.payload: bytes | str | object | None = None
        self.get_error: Exception | None = None
        self.set_error: Exception | None = None
        self.set_calls: list[tuple[str, bytes, int]] = []

    async def get(self, key: str) -> bytes | str | None:
        assert key == DEFAULT_READINESS_CACHE_KEY
        if self.get_error is not None:
            raise self.get_error
        if self.payload is None or isinstance(self.payload, (bytes, str)):
            return self.payload
        return cast(bytes, self.payload)

    async def set(self, key: str, value: bytes, *, ex: int) -> bool | None:
        if self.set_error is not None:
            raise self.set_error
        self.payload = value
        self.set_calls.append((key, value, ex))
        return True


async def _snapshot() -> OperationalReadinessSnapshot:
    service = OperationalReadinessService(
        database=cast(Database, _HealthyPostgresDatabase()),
        context_service=_HealthyContextService(),
        obsidian_service=_HealthyObsidianService(),
        graph_projection_service=HealthyGraphProjectionService(),
    )
    return await service.snapshot()


def test_redis_readiness_cache_round_trips_snapshot_with_ttl() -> None:
    """A valid snapshot should retain its full typed structure through Redis."""

    async def scenario() -> tuple[bool, int, str]:
        client = _FakeRedisClient()
        cache = RedisOperationalReadinessCache(client=client, ttl_seconds=3)
        expected = await _snapshot()

        await cache.set(expected)
        actual = await cache.get()

        return (
            actual == expected,
            client.set_calls[0][2],
            client.set_calls[0][0],
        )

    assert anyio.run(scenario) == (True, 3, DEFAULT_READINESS_CACHE_KEY)


def test_redis_readiness_cache_treats_malformed_payload_as_miss() -> None:
    """Invalid cached JSON should never block authoritative readiness probes."""

    async def scenario() -> OperationalReadinessSnapshot | None:
        client = _FakeRedisClient()
        client.payload = b"not-json"
        cache = RedisOperationalReadinessCache(client=client, ttl_seconds=3)
        return await cache.get()

    assert anyio.run(scenario) is None


def test_redis_readiness_cache_fails_open_when_client_get_fails() -> None:
    """Redis read failures should behave exactly like cache misses."""

    async def scenario() -> OperationalReadinessSnapshot | None:
        client = _FakeRedisClient()
        client.get_error = OSError("redis unavailable")
        cache = RedisOperationalReadinessCache(client=client, ttl_seconds=3)
        return await cache.get()

    assert anyio.run(scenario) is None


def test_redis_readiness_cache_fails_open_when_client_set_fails() -> None:
    """Redis write failures should not change the readiness result path."""

    async def scenario() -> None:
        client = _FakeRedisClient()
        client.set_error = OSError("redis unavailable")
        cache = RedisOperationalReadinessCache(client=client, ttl_seconds=3)
        await cache.set(await _snapshot())

    anyio.run(scenario)


@pytest.mark.parametrize("ttl_seconds", [0, -1])
def test_redis_readiness_cache_rejects_non_positive_ttl(ttl_seconds: int) -> None:
    """Cache entries must always have a finite positive lifetime."""
    with pytest.raises(ValueError, match="TTL must be positive"):
        RedisOperationalReadinessCache(
            client=_FakeRedisClient(),
            ttl_seconds=ttl_seconds,
        )
