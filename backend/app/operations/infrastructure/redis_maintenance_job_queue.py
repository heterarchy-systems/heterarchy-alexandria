"""Redis Streams adapters for bounded maintenance job submission and consumption."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from app.operations.application.maintenance_job_queue import (
    MaintenanceQueueUnavailableError,
    MaintenanceSubmissionRateLimitError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
    MaintenanceQueueSnapshot,
)
from app.operations.infrastructure.maintenance_codec.scalars import (
    RedisValueDecoder,
)
from app.operations.infrastructure.maintenance_codec.snapshots import (
    MaintenanceSnapshotDecoder,
)
from app.operations.infrastructure.maintenance_codec.streams import (
    RedisMaintenanceStreamDecoder,
)
from app.operations.infrastructure.maintenance_queue.keys import (
    dedup_key,
    rate_key,
    status_key,
)
from app.operations.infrastructure.maintenance_queue.mutations import (
    RedisDeadLetterMutationOperations,
)
from app.operations.infrastructure.maintenance_queue.queue_enums import (
    SubmissionReply,
)
from app.operations.infrastructure.maintenance_queue.sources import (
    RedisDeadLetterSourceOperations,
)
from app.operations.infrastructure.redis_maintenance_job_scripts import (
    ENQUEUE_MAINTENANCE_JOB_SCRIPT,
)
from app.platform.config.redis_config import MaintenanceQueueConfig
from app.shared.types.redis_types import RedisHashResponse, RedisResponse


class RedisMaintenanceJobSubmitter(
    RedisDeadLetterSourceOperations,
    RedisDeadLetterMutationOperations,
):
    """API-facing Redis adapter for submission and bounded status reads."""

    def __init__(self, client: Redis, config: MaintenanceQueueConfig) -> None:
        """Bind the Redis Streams client and queue configuration.

        Args:
            client: Async Redis client connected to the maintenance broker.
            config: Validated stream, rate-limit, and deduplication settings.
        """
        self._client = client
        self._config = config

    async def ensure_consumer_group(self) -> None:
        """Create the stream and consumer group idempotently."""
        try:
            operation = self._client.xgroup_create(
                name=self._config.stream_name,
                groupname=self._config.consumer_group,
                id="0-0",
                mkstream=True,
            )
            await cast(Awaitable[bool], operation)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance consumer group creation failed"
                ) from exc
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance queue is unavailable"
            ) from exc

    async def enqueue(self, request: MaintenanceJobRequest) -> MaintenanceJobSnapshot:
        """Submit one atomic rate-limited and deduplicated job.

        Args:
            request: Validated immutable maintenance job submission.

        Returns:
            Immutable queued or deduplicated maintenance job snapshot.
        """
        job_id = uuid.uuid4().hex
        submitted_at = datetime.now(UTC)
        try:
            operation = self._client.eval(
                ENQUEUE_MAINTENANCE_JOB_SCRIPT,
                4,
                dedup_key(self._config, request),
                self._config.stream_name,
                status_key(self._config, job_id),
                rate_key(self._config, request),
                self._config.submission_window_seconds,
                self._config.submission_limit,
                self._config.max_stream_length,
                job_id,
                request.kind.value,
                request.requested_by,
                request.source_id,
                request.limit,
                "1" if request.force else "0",
                submitted_at.isoformat(),
                self._config.dedup_cooldown_seconds,
            )
            raw = await cast(Awaitable[RedisResponse], operation)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance enqueue failed"
            ) from exc
        result = RedisMaintenanceStreamDecoder.decode_enqueue_result(raw)
        if result.state == SubmissionReply.RATE_LIMITED.value:
            raise MaintenanceSubmissionRateLimitError(
                max(1, RedisValueDecoder.integer(result.value, "retry_after"))
            )
        if result.state not in {
            SubmissionReply.QUEUED.value,
            SubmissionReply.DEDUPLICATED.value,
        }:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance enqueue returned an invalid state"
            )
        snapshot = await self.get(result.value)
        if snapshot is None:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance job status was not persisted"
            )
        return replace(
            snapshot, deduplicated=result.state == SubmissionReply.DEDUPLICATED.value
        )

    async def get(self, job_id: str) -> MaintenanceJobSnapshot | None:
        """Read one job snapshot without scanning the Stream.

        Args:
            job_id: Maintenance job identifier.

        Returns:
            Immutable job snapshot, or None when the status hash is absent.
        """
        try:
            operation = self._client.hgetall(status_key(self._config, job_id))
            raw = await cast(Awaitable[RedisHashResponse], operation)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance status lookup failed"
            ) from exc
        return MaintenanceSnapshotDecoder.decode_job_snapshot(raw)

    async def queue_status(self) -> MaintenanceQueueSnapshot:
        """Read aggregate queue evidence without loading queued entries.

        Returns:
            Aggregate Stream, pending, consumer, and dead-letter counts.
        """
        await self.ensure_consumer_group()
        try:
            stream_length_raw = await cast(
                Awaitable[int],
                self._client.xlen(self._config.stream_name),
            )
            pending_raw = await cast(
                Awaitable[RedisResponse],
                self._client.xpending(
                    self._config.stream_name,
                    self._config.consumer_group,
                ),
            )
            consumers_raw = await cast(
                Awaitable[RedisResponse],
                self._client.xinfo_consumers(
                    self._config.stream_name,
                    self._config.consumer_group,
                ),
            )
            dead_letter_raw = await cast(
                Awaitable[int],
                self._client.xlen(self._config.dead_letter_stream_name),
            )
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance queue status failed"
            ) from exc
        return MaintenanceQueueSnapshot(
            stream_length=RedisValueDecoder.integer(stream_length_raw, "stream length"),
            pending=RedisMaintenanceStreamDecoder.decode_pending_count(pending_raw),
            consumers=RedisMaintenanceStreamDecoder.decode_consumer_count(
                consumers_raw
            ),
            dead_letter_length=RedisValueDecoder.integer(
                dead_letter_raw,
                "dead-letter length",
            ),
        )


def create_maintenance_worker_client(config: MaintenanceQueueConfig) -> Redis:
    """Create one small Redis pool sized for the dedicated worker process.

    Args:
        config: Validated worker Redis URL and connection-pool limits.

    Returns:
        Redis client with a worker-specific bounded connection pool.
    """
    if config.redis_url is None:
        raise MaintenanceQueueUnavailableError(
            "SERVICE_REDIS_URL is required by the maintenance worker"
        )
    block_seconds = config.block_milliseconds / 1000
    socket_timeout_seconds = max(10.0, block_seconds + 5.0)
    return Redis.from_url(
        config.redis_url,
        decode_responses=False,
        socket_connect_timeout=0.5,
        socket_timeout=socket_timeout_seconds,
        health_check_interval=30,
        max_connections=config.worker_max_connections,
    )
