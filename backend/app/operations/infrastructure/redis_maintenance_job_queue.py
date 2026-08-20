"""Redis Streams adapters for bounded maintenance job submission and consumption."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol, TypedDict, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from app.operations.application.maintenance_job_queue import (
    MaintenanceJobDelivery,
    MaintenanceQueueUnavailableError,
    MaintenanceSubmissionRateLimitError,
)
from app.operations.domain.entities.maintenance_job import (
    EmbeddingReindexJobResult,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
    MaintenanceQueueSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobStatus,
)
from app.operations.infrastructure.redis_maintenance_job_codec import (
    decode_autoclaim_delivery,
    decode_consumer_count,
    decode_enqueue_result,
    decode_job_snapshot,
    decode_pending_count,
    decode_readgroup_delivery,
    encode_embedding_result,
    response_integer,
)
from app.operations.infrastructure.redis_maintenance_job_scripts import (
    ENQUEUE_MAINTENANCE_JOB_SCRIPT,
)
from app.platform.config.maintenance_queue_config import MaintenanceQueueConfig
from app.shared.types.redis_types import RedisHashResponse, RedisResponse


class MaintenanceStatusMutation(TypedDict, total=False):
    """Known Redis hash mutation fields for one job lifecycle transition."""

    status: str
    started_at: str
    finished_at: str
    result_json: bytes
    error_summary: str


class MaintenanceDeadLetterFields(TypedDict):
    """Bounded terminal failure fields stored in the dead-letter stream."""

    job_id: str
    kind: str
    attempts: str
    failed_at: str
    error_summary: str
    source_stream_id: str


class RedisStreamWriter(Protocol):
    """Narrow async XADD boundary used to isolate redis-py generic stubs."""

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str | bytes:
        """Append one bounded stream entry.

        Args:
            name: Redis Stream key.
            fields: String field mapping written to the Stream entry.
            maxlen: Approximate maximum Stream length.
            approximate: Whether Redis may trim approximately for bounded cost.

        Returns:
            Redis Stream entry identifier.
        """


class RedisMaintenanceJobSubmitter:
    """API-facing Redis adapter for submission and bounded status reads."""

    def __init__(self, client: Redis, config: MaintenanceQueueConfig) -> None:
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
                _dedup_key(self._config, request),
                self._config.stream_name,
                _status_key(self._config, job_id),
                _rate_key(self._config, request),
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
                self._config.status_ttl_seconds,
                self._config.dedup_cooldown_seconds,
            )
            raw = await cast(Awaitable[RedisResponse], operation)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance enqueue failed"
            ) from exc
        result = decode_enqueue_result(raw)
        if result.state == "RATE_LIMITED":
            raise MaintenanceSubmissionRateLimitError(
                max(1, response_integer(result.value, "retry_after"))
            )
        if result.state not in {"QUEUED", "DEDUPLICATED"}:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance enqueue returned an invalid state"
            )
        snapshot = await self.get(result.value)
        if snapshot is None:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance job status was not persisted"
            )
        return replace(snapshot, deduplicated=result.state == "DEDUPLICATED")

    async def get(self, job_id: str) -> MaintenanceJobSnapshot | None:
        """Read one job snapshot without scanning the Stream.

        Args:
            job_id: Maintenance job identifier.

        Returns:
            Immutable job snapshot, or None when the status hash is absent.
        """
        try:
            operation = self._client.hgetall(_status_key(self._config, job_id))
            raw = await cast(Awaitable[RedisHashResponse], operation)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance status lookup failed"
            ) from exc
        return decode_job_snapshot(raw)

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
            stream_length=response_integer(stream_length_raw, "stream length"),
            pending=decode_pending_count(pending_raw),
            consumers=decode_consumer_count(consumers_raw),
            dead_letter_length=response_integer(
                dead_letter_raw,
                "dead-letter length",
            ),
        )


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
    return Redis.from_url(
        config.redis_url,
        decode_responses=False,
        socket_connect_timeout=0.5,
        socket_timeout=block_seconds + 1.0,
        health_check_interval=30,
        max_connections=config.worker_max_connections,
    )


def _status_key(config: MaintenanceQueueConfig, job_id: str) -> str:
    return f"{config.status_key_prefix}:{job_id}"


def _dedup_key(
    config: MaintenanceQueueConfig,
    request: MaintenanceJobRequest,
) -> str:
    material = "\x1f".join(
        (
            request.kind.value,
            request.requested_by,
            request.source_id,
            str(request.limit),
            "1" if request.force else "0",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{config.dedup_key_prefix}:{digest}"


def _rate_key(
    config: MaintenanceQueueConfig,
    request: MaintenanceJobRequest,
) -> str:
    material = f"{request.kind.value}\x1f{request.requested_by}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{config.rate_key_prefix}:maintenance:{digest}"


def _status_mapping(fields: MaintenanceStatusMutation) -> dict[str, str | bytes]:
    mapping: dict[str, str | bytes] = {}
    if "status" in fields:
        mapping["status"] = fields["status"]
    if "started_at" in fields:
        mapping["started_at"] = fields["started_at"]
    if "finished_at" in fields:
        mapping["finished_at"] = fields["finished_at"]
    if "result_json" in fields:
        mapping["result_json"] = fields["result_json"]
    if "error_summary" in fields:
        mapping["error_summary"] = fields["error_summary"]
    return mapping


def _dead_letter_mapping(fields: MaintenanceDeadLetterFields) -> dict[str, str]:
    return {
        "job_id": fields["job_id"],
        "kind": fields["kind"],
        "attempts": fields["attempts"],
        "failed_at": fields["failed_at"],
        "error_summary": fields["error_summary"],
        "source_stream_id": fields["source_stream_id"],
    }
