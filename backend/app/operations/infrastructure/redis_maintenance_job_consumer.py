"""Redis maintenance job consumer."""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.operations.application.maintenance_job_queue import (
    MaintenanceJobDelivery,
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    EmbeddingReindexJobResult,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobStatus,
)
from app.operations.infrastructure.redis_maintenance_job_codec import (
    decode_autoclaim_delivery,
    decode_readgroup_delivery,
    encode_embedding_result,
    response_integer,
)
from app.operations.infrastructure.redis_maintenance_job_queue import (
    MaintenanceDeadLetterFields,
    MaintenanceStatusMutation,
    RedisMaintenanceJobSubmitter,
    RedisStreamWriter,
    _dead_letter_mapping,
    _status_key,
    _status_mapping,
)
from app.platform.config.maintenance_queue_config import MaintenanceQueueConfig
from app.shared.types.redis_types import RedisResponse


class RedisMaintenanceJobConsumer:
    """Worker-facing Redis adapter for claim, retry, and acknowledgement."""

    def __init__(
        self,
        client: Redis,
        config: MaintenanceQueueConfig,
        submitter: RedisMaintenanceJobSubmitter,
    ) -> None:
        self._client = client
        self._config = config
        self._submitter = submitter

    async def ensure_consumer_group(self) -> None:
        """Create the stream and consumer group idempotently."""
        await self._submitter.ensure_consumer_group()

    async def receive(self, consumer_name: str) -> MaintenanceJobDelivery | None:
        """Claim one stale pending job before reading one new entry.

        Args:
            consumer_name: Unique consumer name for the worker loop.

        Returns:
            Claimed job delivery, or None when no work is available.
        """
        await self.ensure_consumer_group()
        try:
            claimed_raw = await cast(
                Awaitable[RedisResponse],
                self._client.xautoclaim(
                    name=self._config.stream_name,
                    groupname=self._config.consumer_group,
                    consumername=consumer_name,
                    min_idle_time=self._config.retry_idle_seconds * 1000,
                    start_id="0-0",
                    count=1,
                ),
            )
            decoded = decode_autoclaim_delivery(claimed_raw)
            if decoded is None:
                read_raw = await cast(
                    Awaitable[RedisResponse],
                    self._client.xreadgroup(
                        groupname=self._config.consumer_group,
                        consumername=consumer_name,
                        streams={self._config.stream_name: ">"},
                        count=1,
                        block=self._config.block_milliseconds,
                    ),
                )
                decoded = decode_readgroup_delivery(read_raw)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance receive failed"
            ) from exc
        if decoded is None:
            return None
        snapshot = await self._submitter.get(decoded.job_id)
        if snapshot is None:
            await self._ack(decoded.stream_id)
            return None
        return MaintenanceJobDelivery(stream_id=decoded.stream_id, job=snapshot)

    async def mark_running(self, delivery: MaintenanceJobDelivery) -> int:
        """Increment the attempt count and persist RUNNING state.

        Args:
            delivery: Claimed maintenance job and Redis stream identifier.

        Returns:
            Persisted one-based execution attempt number.
        """
        key = _status_key(self._config, delivery.job.job_id)
        now = datetime.now(UTC).isoformat()
        mutation: MaintenanceStatusMutation = {
            "status": MaintenanceJobStatus.RUNNING.value,
            "started_at": now,
            "finished_at": "",
            "error_summary": "",
        }
        try:
            attempt_raw = await cast(
                Awaitable[int],
                self._client.hincrby(key, "attempts", 1),
            )
            await cast(
                Awaitable[int],
                self._client.hset(key, mapping=_status_mapping(mutation)),
            )
            await cast(
                Awaitable[bool],
                self._client.expire(key, self._config.status_ttl_seconds),
            )
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance running transition failed"
            ) from exc
        return response_integer(attempt_raw, "attempt")

    async def mark_succeeded(
        self,
        delivery: MaintenanceJobDelivery,
        result: EmbeddingReindexJobResult,
    ) -> None:
        """Persist a bounded result and acknowledge the Stream entry.

        Args:
            delivery: Claimed maintenance job and Redis stream identifier.
            result: Bounded embedding reindex result to persist.
        """
        key = _status_key(self._config, delivery.job.job_id)
        mutation: MaintenanceStatusMutation = {
            "status": MaintenanceJobStatus.SUCCEEDED.value,
            "finished_at": datetime.now(UTC).isoformat(),
            "result_json": encode_embedding_result(result),
            "error_summary": "",
        }
        try:
            await cast(
                Awaitable[int],
                self._client.hset(key, mapping=_status_mapping(mutation)),
            )
            await cast(
                Awaitable[bool],
                self._client.expire(key, self._config.status_ttl_seconds),
            )
            await self._ack(delivery.stream_id)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance success transition failed"
            ) from exc

    async def mark_failed(
        self,
        delivery: MaintenanceJobDelivery,
        attempt: int,
        error_summary: str,
    ) -> bool:
        """Keep retryable work pending or move terminal evidence to the DLQ.

        Args:
            delivery: Claimed maintenance job and Redis stream identifier.
            attempt: Current one-based execution attempt number.
            error_summary: Bounded operator-safe failure summary.

        Returns:
            True when the job moved to terminal failure; False when retryable.
        """
        key = _status_key(self._config, delivery.job.job_id)
        bounded_error = error_summary[:1000]
        terminal = attempt >= self._config.max_attempts
        mutation: MaintenanceStatusMutation = {
            "status": (
                MaintenanceJobStatus.FAILED.value
                if terminal
                else MaintenanceJobStatus.RETRYING.value
            ),
            "error_summary": bounded_error,
        }
        if terminal:
            mutation["finished_at"] = datetime.now(UTC).isoformat()
        try:
            await cast(
                Awaitable[int],
                self._client.hset(key, mapping=_status_mapping(mutation)),
            )
            await cast(
                Awaitable[bool],
                self._client.expire(key, self._config.status_ttl_seconds),
            )
            if terminal:
                dead_letter: MaintenanceDeadLetterFields = {
                    "job_id": delivery.job.job_id,
                    "kind": delivery.job.kind.value,
                    "attempts": str(attempt),
                    "failed_at": datetime.now(UTC).isoformat(),
                    "error_summary": bounded_error,
                    "source_stream_id": delivery.stream_id,
                }
                writer = cast(RedisStreamWriter, self._client)
                await writer.xadd(
                    self._config.dead_letter_stream_name,
                    _dead_letter_mapping(dead_letter),
                    maxlen=self._config.max_stream_length,
                    approximate=True,
                )
                await self._ack(delivery.stream_id)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance failure transition failed"
            ) from exc
        return terminal

    async def _ack(self, stream_id: str) -> None:
        operation = self._client.xack(
            self._config.stream_name,
            self._config.consumer_group,
            stream_id,
        )
        await cast(Awaitable[int], operation)
