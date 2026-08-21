"""Process-scoped Redis budget for outbound provider API calls."""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.operations.infrastructure.redis_fixed_window_rate_limiter import (
    RedisFixedWindowRateLimiter,
)

_PROVIDER_PATTERN = re.compile(r"[^a-z0-9_.-]+")


class ExternalApiRateLimitError(RuntimeError):
    """Base error for provider budget rejection or Redis unavailability."""


class ExternalApiRateLimitedError(ExternalApiRateLimitError):
    """Raised when an outbound provider has exhausted its Redis budget."""

    def __init__(self, provider: str, retry_after_seconds: int) -> None:
        super().__init__(f"external API rate limit exceeded for {provider}")
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds


class ExternalApiRateLimiterUnavailableError(ExternalApiRateLimitError):
    """Raised when a configured fail-closed provider budget cannot use Redis."""


class ExternalApiRateLimiter(Protocol):
    """Async permit boundary used immediately before provider network calls."""

    async def acquire(
        self,
        provider: str,
        subject: str,
        limit: int | None = None,
    ) -> None:
        """Consume one permit or raise an explicit rate-limit error.

        Args:
            provider: External provider budget namespace.
            subject: Stable caller or workload identity.
            limit: Optional permit limit overriding the configured default.
        """


class NoopExternalApiRateLimiter:
    """Disabled provider budget used when Redis is not configured."""

    async def acquire(
        self,
        provider: str,
        subject: str,
        limit: int | None = None,
    ) -> None:
        del provider, subject, limit


class RedisExternalApiRateLimiter:
    """Shared-client fixed-window budget for outbound provider calls."""

    def __init__(
        self,
        client: Redis,
        default_limit: int,
        window_seconds: int,
        key_prefix: str = "alexandria:rate:v1",
    ) -> None:
        self._limiter = RedisFixedWindowRateLimiter(client, key_prefix)
        self._default_limit = default_limit
        self._window_seconds = window_seconds

    async def acquire(
        self,
        provider: str,
        subject: str,
        limit: int | None = None,
    ) -> None:
        """Consume one fail-closed provider permit.

        Args:
            provider: External provider budget namespace.
            subject: Stable caller or workload identity.
            limit: Optional permit limit overriding the configured default.
        """
        normalized_provider = _normalized_provider(provider)
        subject_digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        try:
            decision = await self._limiter.acquire(
                f"external-api:{normalized_provider}",
                subject_digest,
                self._default_limit if limit is None else limit,
                self._window_seconds,
            )
        except (RedisError, RuntimeError, ValueError) as exc:
            raise ExternalApiRateLimiterUnavailableError(
                f"external API rate limiter unavailable for {normalized_provider}"
            ) from exc
        if not decision.allowed:
            raise ExternalApiRateLimitedError(
                normalized_provider,
                decision.retry_after_seconds,
            )


def _normalized_provider(provider: str) -> str:
    normalized = _PROVIDER_PATTERN.sub("-", provider.strip().lower()).strip("-")
    if not normalized:
        raise ValueError("provider must contain at least one supported character")
    return normalized
