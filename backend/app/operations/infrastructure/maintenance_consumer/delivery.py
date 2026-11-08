"""Redis consumer delivery responsibilities."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable

from redis.asyncio import Redis

from app.operations.application.maintenance_job_queue import (
    MaintenanceJobDelivery,
    MaintenanceQueueUnavailableError,
)
from app.operations.infrastructure.maintenance_codec.contracts import (
    RedisStreamDelivery,
)
from app.operations.infrastructure.maintenance_codec.streams import (
    RedisMaintenanceStreamDecoder,
)
from app.operations.infrastructure.maintenance_consumer.policy import (
    CONSUMER_LOGGER_NAME,
    MaintenanceDeliveryLogFields,
)
from app.operations.infrastructure.maintenance_consumer.responses import (
    MaintenanceConsumerResponseDecoder,
)
from app.operations.infrastructure.redis_maintenance_job_queue import (
    RedisMaintenanceJobSubmitter,
)
from app.platform.config.redis_config import MaintenanceQueueConfig
from app.shared.types.redis_types import RedisResponse

logger = logging.getLogger(CONSUMER_LOGGER_NAME)


class MaintenanceDeliveryReader:
    """Own the one claim cursor and lock for a consumer."""

    def __init__(
        self,
        client: Redis,
        config: MaintenanceQueueConfig,
        submitter: RedisMaintenanceJobSubmitter,
    ) -> None:
        """Initialize the delivery reader with Redis client, config, and submitter.

        Args:
            client: Async Redis client connected to the maintenance stream.
            config: Maintenance queue stream and consumer group settings.
            submitter: Status reader for claimed job snapshots.
        """
        self._client = client
        self._config = config
        self._submitter = submitter
        self._autoclaim_cursor = "0-0"
        self._autoclaim_lock = asyncio.Lock()

    async def claim_stale(self, consumer_name: str) -> RedisStreamDelivery | None:
        """Claim one stale entry and advance the bounded PEL scan cursor.

        Args:
            consumer_name: Consumer identifier claiming the pending entry.

        Returns:
            Decoded stream delivery if one stale entry was claimed, or None.

        Raises:
            MaintenanceQueueUnavailableError: If the Redis XAUTOCLAIM response is invalid.
        """
        async with self._autoclaim_lock:
            operation = self._client.xautoclaim(
                name=self._config.stream_name,
                groupname=self._config.consumer_group,
                consumername=consumer_name,
                min_idle_time=self._config.retry_idle_seconds * 1000,
                start_id=self._autoclaim_cursor,
                count=1,
            )
            if not isinstance(operation, Awaitable):
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance autoclaim did not return an awaitable"
                )
            raw: RedisResponse = await operation
            self._autoclaim_cursor = (
                MaintenanceConsumerResponseDecoder.autoclaim_next_cursor(raw)
            )
        return RedisMaintenanceStreamDecoder.decode_autoclaim_delivery(raw)

    async def delivery_for(
        self, stream_id: str, job_id: str
    ) -> MaintenanceJobDelivery | None:
        """Load status evidence without acknowledging or reconstructing missing state.

        Args:
            stream_id: Redis Stream entry ID.
            job_id: Maintenance job identifier carried by the stream entry.

        Returns:
            Hydrated job delivery when status is readable and matches `job_id`, or None.
        """
        try:
            snapshot = await self._submitter.get(job_id)
        except (MaintenanceQueueUnavailableError, ValueError) as exc:
            logger.warning(
                "maintenance delivery status is unreadable; delivery remains pending",
                extra=MaintenanceDeliveryLogFields(job_id=job_id, stream_id=stream_id),
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return None
        if snapshot is None or snapshot.job_id != job_id:
            logger.warning(
                "maintenance delivery has no matching status; delivery remains pending",
                extra=MaintenanceDeliveryLogFields(job_id=job_id, stream_id=stream_id),
            )
            return None
        return MaintenanceJobDelivery(stream_id=stream_id, job=snapshot)
