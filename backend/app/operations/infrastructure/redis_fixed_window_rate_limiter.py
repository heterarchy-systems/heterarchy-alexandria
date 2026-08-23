"""Small Redis fixed-window limiter for execution budgets."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast

from redis.asyncio import Redis

from app.shared.types.redis_types import RedisResponse

_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class RateLimitDecision:
    """One Redis-backed fixed-window decision."""

    allowed: bool
    remaining: int
    retry_after_seconds: int


class RedisFixedWindowRateLimiter:
    """Enforce bounded execution counts without participating in locking."""

    def __init__(self, client: Redis, key_prefix: str) -> None:
        """Initialize RedisFixedWindowRateLimiter state and dependencies.

        Args:
            client: Client used by this operation.
            key_prefix: Key prefix used by this operation.
        """
        self._client = client
        self._key_prefix = key_prefix.rstrip(":")

    async def acquire(
        self,
        scope: str,
        subject: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        """Consume one fixed-window permit.

        Args:
            scope: Rate-limit namespace such as an external provider operation.
            subject: Stable caller or workload identity.
            limit: Maximum permits allowed in the window.
            window_seconds: Fixed-window duration in seconds.

        Returns:
            Permit decision with remaining capacity and retry delay.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        if window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        key = f"{self._key_prefix}:{scope}:{subject}"
        operation = self._client.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            key,
            window_seconds,
        )
        raw = await cast(Awaitable[RedisResponse], operation)
        current, ttl = _parse_rate_limit_response(raw)
        return RateLimitDecision(
            allowed=current <= limit,
            remaining=max(0, limit - current),
            retry_after_seconds=max(1, ttl),
        )


def _parse_rate_limit_response(value: RedisResponse) -> tuple[int, int]:
    """Parse rate limit response.

    Args:
        value: Value being processed.

    Returns:
        Parsed rate limit response.
    """
    if not isinstance(value, list | tuple):
        raise RuntimeError("Redis rate-limit response must be a sequence")
    if len(value) != 2:
        raise RuntimeError("Redis rate-limit response must contain two values")
    return (
        _integer_response(value[0], "current"),
        _integer_response(value[1], "ttl"),
    )


def _integer_response(value: RedisResponse, field: str) -> int:
    """Execute integer response.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        int result produced by integer response.
    """
    if isinstance(value, bool):
        raise RuntimeError(f"Redis {field} response was boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"Redis {field} response was not UTF-8") from exc
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise RuntimeError(f"Redis {field} response was not numeric") from exc
    raise RuntimeError(f"Redis {field} response had an invalid type")
