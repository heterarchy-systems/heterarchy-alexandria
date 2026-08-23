"""Fail-open Redis adapter for short-lived readiness snapshots."""

from __future__ import annotations

import logging
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from app.operations.application.readiness.operational_readiness_cache import (
    OperationalReadinessCache,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)

logger = logging.getLogger(__name__)

DEFAULT_READINESS_CACHE_KEY = "alexandria:operations:readiness:v1"
_SNAPSHOT_ADAPTER = TypeAdapter(OperationalReadinessSnapshot)


# protocol-contract: structural-seam
class RedisReadinessClient(Protocol):
    """Narrow Redis command surface required by the readiness cache."""

    async def get(self, key: str) -> bytes | str | None:
        """Return one raw cached value.

        Args:
            key: Versioned Redis cache key.

        Returns:
            Raw bytes or text, or None on a cache miss.
        """

    async def set(
        self,
        key: str,
        value: bytes,
        ex: int,
    ) -> bool | None:
        """Store one value with a bounded lifetime.

        Args:
            key: Versioned Redis cache key.
            value: Serialized readiness snapshot.
            ex: Positive expiry duration in seconds.

        Returns:
            Redis acknowledgement when the client exposes one.
        """


class RedisOperationalReadinessCache(OperationalReadinessCache):
    """Cache readiness snapshots without participating in correctness."""

    def __init__(
        self,
        client: RedisReadinessClient,
        ttl_seconds: int,
        key: str = DEFAULT_READINESS_CACHE_KEY,
    ) -> None:
        """Initialize the cache adapter.

        Args:
            client: Narrow asynchronous Redis client.
            ttl_seconds: Positive cache lifetime in seconds.
            key: Versioned Redis key for the readiness payload.
        """
        if ttl_seconds <= 0:
            raise ValueError("readiness cache TTL must be positive")
        if not key:
            raise ValueError("readiness cache key must not be blank")
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._key = key

    async def get(self) -> OperationalReadinessSnapshot | None:
        """Return a validated cached snapshot or fail open as a cache miss.

        Returns:
            Validated cached snapshot, or None when unavailable or invalid.
        """
        try:
            payload = await self._client.get(self._key)
        except Exception as exc:  # Cache is an optional external boundary.
            self._log_failure(operation="get", error=exc)
            return None
        if payload is None:
            return None
        if not isinstance(payload, (bytes, str)):
            logger.warning(
                "Redis readiness cache returned an unsupported payload type",
                extra={
                    "operation": "readiness_cache_get",
                    "payload_type": type(payload).__name__,
                },
            )
            return None
        try:
            return _SNAPSHOT_ADAPTER.validate_json(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            self._log_failure(operation="decode", error=exc)
            return None

    async def set(self, snapshot: OperationalReadinessSnapshot) -> None:
        """Store one snapshot and suppress optional cache failures.

        Args:
            snapshot: Fresh authoritative readiness snapshot.
        """
        try:
            payload = _SNAPSHOT_ADAPTER.dump_json(snapshot)
            await self._client.set(
                self._key,
                payload,
                ex=self._ttl_seconds,
            )
        except Exception as exc:  # Cache is an optional external boundary.
            self._log_failure(operation="set", error=exc)

    @staticmethod
    def _log_failure(operation: str, error: Exception) -> None:
        """Execute log failure.

        Args:
            operation: Operation used by this operation.
            error: Error value being processed.
        """
        logger.warning(
            "Redis readiness cache operation failed and will be bypassed",
            extra={
                "operation": f"readiness_cache_{operation}",
                "error_type": type(error).__name__,
            },
        )
