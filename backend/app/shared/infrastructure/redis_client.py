"""Optional shared redis-py client lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from redis.asyncio import Redis


# protocol-contract: structural-seam
class RedisConnectionSettings(Protocol):
    """Minimal settings contract required by the shared Redis lifecycle."""

    url: str | None
    max_connections: int


def create_redis_client(redis_url: str, max_connections: int = 8) -> Redis:
    """Create one lazy asynchronous Redis client.

    Args:
        redis_url: Redis connection URL.

        max_connections: Maximum Redis connections allowed in the pool.
    Returns:
        Lazy redis-py client with bounded command timeouts.
    """
    return Redis.from_url(
        redis_url,
        decode_responses=False,
        socket_connect_timeout=0.25,
        socket_timeout=0.75,
        health_check_interval=30,
        max_connections=max_connections,
    )


@asynccontextmanager
async def initialize_redis_client(
    config: RedisConnectionSettings,
) -> AsyncIterator[Redis | None]:
    """Provision and close one optional process-wide Redis client.

    Args:
        config: Validated optional Redis settings.

    Yields:
        Shared Redis client, or ``None`` when Redis is disabled.
    """
    if config.url is None:
        yield None
        return
    client = create_redis_client(config.url, config.max_connections)
    try:
        yield client
    finally:
        await client.aclose()
