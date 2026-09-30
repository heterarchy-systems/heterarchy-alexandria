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
    MaintenanceDeadLetterLifecycleConflictError,
    MaintenanceDeadLetterNotFoundError,
    MaintenanceDeadLetterSourceGoneError,
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
    MaintenanceSubmissionRateLimitError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterContext,
    MaintenanceDeadLetterEntry,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
    MaintenanceQueueSnapshot,
)
from app.operations.infrastructure.redis_maintenance_job_codec import (
    decode_consumer_count,
    decode_dead_letter_entries,
    decode_dead_letter_source_request,
    decode_dead_letter_transition,
    decode_enqueue_result,
    decode_job_snapshot,
    decode_pending_count,
    response_integer,
)
from app.operations.infrastructure.redis_maintenance_job_scripts import (
    ENQUEUE_MAINTENANCE_JOB_SCRIPT,
    FINALIZE_MAINTENANCE_DEAD_LETTER_SCRIPT,
    RESERVE_MAINTENANCE_DEAD_LETTER_SCRIPT,
    RETRY_MAINTENANCE_DEAD_LETTER_SCRIPT,
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
    attempt_history_json: bytes
    last_retry_reason: str
    last_retry_at: str
    dlq_state: str


class MaintenanceDeadLetterFields(TypedDict):
    """Bounded terminal failure fields stored in the dead-letter stream."""

    job_id: str
    kind: str
    attempts: str
    failed_at: str
    error_summary: str
    source_stream_id: str
    attempt_history_json: str


# protocol-contract: structural-seam
class RedisStreamWriter(Protocol):
    """Narrow async XADD boundary used to isolate redis-py generic stubs."""

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
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


class RedisMaintenanceJobSubmitter(MaintenanceJobSubmitter):
    """API-facing Redis adapter for submission and bounded status reads."""

    def __init__(self, client: Redis, config: MaintenanceQueueConfig) -> None:
        """Initialize RedisMaintenanceJobSubmitter state and dependencies.

        Args:
            client: Client used by this operation.
            config: Typed configuration used by this operation.
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

    async def list_dead_letters(
        self, limit: int
    ) -> tuple[MaintenanceDeadLetterEntry, ...]:
        """Read the newest dead-letter entries without mutating the stream.

        Args:
            limit: Requested entry count, clamped to the bounded maximum.

        Returns:
            Newest-first dead-letter entries.
        """
        bounded_limit = max(1, min(limit, 200))
        try:
            raw = await cast(
                Awaitable[RedisResponse],
                self._client.xrevrange(
                    self._config.dead_letter_stream_name,
                    max="+",
                    min="-",
                    count=bounded_limit,
                ),
            )
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter read failed"
            ) from exc
        return decode_dead_letter_entries(raw)

    async def purge_dead_letters(self) -> int:
        """Drop every dead-letter entry and report the removed count.

        Returns:
            Number of dead-letter entries present before the purge.
        """
        try:
            length_raw = await cast(
                Awaitable[int],
                self._client.xlen(self._config.dead_letter_stream_name),
            )
            await cast(
                Awaitable[int],
                self._client.xtrim(
                    self._config.dead_letter_stream_name,
                    maxlen=0,
                    approximate=False,
                ),
            )
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter purge failed"
            ) from exc
        return response_integer(length_raw, "dead-letter length")

    async def replay_dead_letter(self, entry_id: str) -> MaintenanceJobSnapshot:
        """Re-enqueue the request behind one dead-letter entry as a new job.

        Args:
            entry_id: Dead-letter stream entry identifier.

        Returns:
            Freshly queued replacement job snapshot.
        """
        letter_raw = await self._range_entry(
            self._config.dead_letter_stream_name,
            entry_id,
        )
        letters = decode_dead_letter_entries(letter_raw)
        if not letters:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        letter = letters[0]
        source_raw = await self._range_entry(
            self._config.stream_name,
            letter.source_stream_id,
        )
        request = decode_dead_letter_source_request(source_raw)
        if request is None:
            raise MaintenanceDeadLetterSourceGoneError(
                "dead-letter source entry is no longer available for replay"
            )
        return await self.enqueue(request)

    async def get_dead_letter(
        self, entry_id: str
    ) -> MaintenanceDeadLetterContext | None:
        """Read one exact DLQ entry, its original job, and source request."""
        letter_raw = await self._range_entry(
            self._config.dead_letter_stream_name,
            entry_id,
        )
        letters = decode_dead_letter_entries(letter_raw)
        if not letters:
            return None
        entry = letters[0]
        try:
            lifecycle_raw = await cast(
                Awaitable[RedisResponse],
                self._client.get(_dead_letter_lifecycle_key(self._config, entry_id)),
            )
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter lifecycle lookup failed"
            ) from exc
        lifecycle = (
            _text_response(lifecycle_raw)
            if lifecycle_raw is not None
            else entry.lifecycle
        )
        entry = replace(entry, lifecycle=lifecycle)
        original_job = await self.get(entry.job_id)
        source_raw = await self._range_entry(
            self._config.stream_name,
            entry.source_stream_id,
        )
        try:
            source_request = decode_dead_letter_source_request(source_raw)
        except MaintenanceQueueUnavailableError:
            # Redis read succeeded but the retained source shape is corrupt;
            # callers must classify it as unknown/non-retryable evidence.
            source_request = None
        return MaintenanceDeadLetterContext(
            entry=entry,
            original_job=original_job,
            source_request=source_request,
        )

    async def retry_dead_letter(
        self, entry_id: str, reason: str
    ) -> MaintenanceJobSnapshot:
        """Requeue one terminal job under its original identity through Lua CAS."""
        bounded_reason = reason.strip()[:500]
        if not bounded_reason:
            raise ValueError("dead-letter retry reason must not be blank")
        context = await self.get_dead_letter(entry_id)
        if context is None:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        if context.source_request is None:
            raise MaintenanceDeadLetterSourceGoneError(
                "dead-letter source request is unavailable for same-ID retry"
            )
        try:
            operation = self._client.eval(
                RETRY_MAINTENANCE_DEAD_LETTER_SCRIPT,
                4,
                _status_key(self._config, context.entry.job_id),
                self._config.stream_name,
                self._config.dead_letter_stream_name,
                _dead_letter_lifecycle_key(self._config, entry_id),
                entry_id,
                self._config.max_stream_length,
                bounded_reason,
                datetime.now(UTC).isoformat(),
                self._config.status_ttl_seconds,
                self._config.consumer_group,
            )
            raw = await cast(Awaitable[RedisResponse], operation)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter retry transition failed"
            ) from exc
        state, job_id, detail = decode_dead_letter_transition(raw)
        if state == "NOT_FOUND":
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        if state == "CONFLICT":
            raise MaintenanceDeadLetterLifecycleConflictError(
                f"dead-letter retry lifecycle conflict: {detail or job_id}"
            )
        if state not in {"QUEUED", "IDEMPOTENT"} or not job_id:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter retry transition returned an invalid state"
            )
        snapshot = await self.get(job_id)
        if snapshot is None:
            raise MaintenanceQueueUnavailableError(
                "Redis retried maintenance job status was not persisted"
            )
        return snapshot

    async def reserve_dead_letter_retirement(
        self, entry_id: str
    ) -> MaintenanceDeadLetterContext:
        """Reserve one failed entry before PostgreSQL provenance archival."""
        context = await self.get_dead_letter(entry_id)
        if context is None:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        try:
            operation = self._client.eval(
                RESERVE_MAINTENANCE_DEAD_LETTER_SCRIPT,
                4,
                _status_key(self._config, context.entry.job_id),
                self._config.dead_letter_stream_name,
                _dead_letter_lifecycle_key(self._config, entry_id),
                self._config.stream_name,
                entry_id,
                self._config.consumer_group,
                context.entry.source_stream_id,
            )
            raw = await cast(Awaitable[RedisResponse], operation)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter retirement reservation failed"
            ) from exc
        state, _value, detail = decode_dead_letter_transition(raw)
        if state == "NOT_FOUND":
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        if state not in {"RETIRING", "RETIRED"}:
            raise MaintenanceDeadLetterLifecycleConflictError(
                f"dead-letter retirement lifecycle conflict: {detail or state}"
            )
        return replace(context, entry=replace(context.entry, lifecycle=state))

    async def finalize_dead_letter_retirement(
        self,
        entry_id: str,
        source_stream_id: str,
        job_id: str | None = None,
    ) -> bool:
        """Delete exactly one reserved DLQ/source pair and seal RETIRED state."""
        context = await self.get_dead_letter(entry_id)
        resolved_job_id = job_id or (
            context.entry.job_id if context is not None else None
        )
        if resolved_job_id is None:
            raise MaintenanceDeadLetterNotFoundError(
                "dead-letter entry has no retained job identity"
            )
        try:
            operation = self._client.eval(
                FINALIZE_MAINTENANCE_DEAD_LETTER_SCRIPT,
                4,
                _status_key(self._config, resolved_job_id),
                self._config.dead_letter_stream_name,
                self._config.stream_name,
                _dead_letter_lifecycle_key(self._config, entry_id),
                entry_id,
                source_stream_id,
            )
            raw = await cast(Awaitable[RedisResponse], operation)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter retirement cleanup failed"
            ) from exc
        state, _removed_dlq, _removed_source = decode_dead_letter_transition(raw)
        if state == "ALREADY_RETIRED" or state == "RETIRED":
            return True
        if state == "CONFLICT":
            raise MaintenanceDeadLetterLifecycleConflictError(
                "dead-letter retirement cleanup lost its lifecycle reservation"
            )
        raise MaintenanceQueueUnavailableError(
            "Redis dead-letter retirement cleanup returned an invalid state"
        )

    async def _range_entry(self, stream: str, entry_id: str) -> RedisResponse:
        """Read exactly one stream entry by identifier.

        Args:
            stream: Redis Stream key to read.
            entry_id: Exact stream entry identifier to fetch.

        Returns:
            Raw Redis range response with zero or one entries.
        """
        try:
            raw = await cast(
                Awaitable[RedisResponse],
                self._client.xrange(stream, min=entry_id, max=entry_id),
            )
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter read failed"
            ) from exc
        return raw


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


def _status_key(config: MaintenanceQueueConfig, job_id: str) -> str:
    """Execute status key.

    Args:
        config: Typed configuration used by this operation.
        job_id: Identifier for job.

    Returns:
        str result produced by status key.
    """
    return f"{config.status_key_prefix}:{job_id}"


def _dead_letter_lifecycle_key(config: MaintenanceQueueConfig, entry_id: str) -> str:
    """Return the non-expiring per-entry lifecycle reservation key."""
    return f"{config.dead_letter_stream_name}:lifecycle:{entry_id}"


def _text_response(value: RedisResponse) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise MaintenanceQueueUnavailableError("Redis dead-letter lifecycle is invalid")


def _dedup_key(
    config: MaintenanceQueueConfig,
    request: MaintenanceJobRequest,
) -> str:
    """Execute dedup key.

    Args:
        config: Typed configuration used by this operation.
        request: Validated request for this operation.

    Returns:
        str result produced by dedup key.
    """
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
    """Execute rate key.

    Args:
        config: Typed configuration used by this operation.
        request: Validated request for this operation.

    Returns:
        str result produced by rate key.
    """
    material = f"{request.kind.value}\x1f{request.requested_by}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{config.rate_key_prefix}:maintenance:{digest}"


def _status_mapping(fields: MaintenanceStatusMutation) -> dict[str, str | bytes]:
    """Execute status mapping.

    Args:
        fields: Fields used by this operation.

    Returns:
        dict[str, str | bytes] result produced by status mapping.
    """
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
    if "attempt_history_json" in fields:
        mapping["attempt_history_json"] = fields["attempt_history_json"]
    if "last_retry_reason" in fields:
        mapping["last_retry_reason"] = fields["last_retry_reason"]
    if "last_retry_at" in fields:
        mapping["last_retry_at"] = fields["last_retry_at"]
    if "dlq_state" in fields:
        mapping["dlq_state"] = fields["dlq_state"]
    return mapping


def _dead_letter_mapping(fields: MaintenanceDeadLetterFields) -> dict[str, str]:
    """Execute dead letter mapping.

    Args:
        fields: Fields used by this operation.

    Returns:
        dict[str, str] result produced by dead letter mapping.
    """
    return {
        "job_id": fields["job_id"],
        "kind": fields["kind"],
        "attempts": fields["attempts"],
        "failed_at": fields["failed_at"],
        "error_summary": fields["error_summary"],
        "source_stream_id": fields["source_stream_id"],
        "attempt_history_json": fields["attempt_history_json"],
    }
