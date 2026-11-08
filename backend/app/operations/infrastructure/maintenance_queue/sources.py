"""Source-owned Redis dead-letter operations."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import replace
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.operations.application.maintenance_job_queue import (
    MaintenanceDeadLetterNotFoundError,
    MaintenanceDeadLetterSourceGoneError,
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterContext,
    MaintenanceDeadLetterEntry,
    MaintenanceJobSnapshot,
)
from app.operations.infrastructure.maintenance_codec.streams import (
    RedisDeadLetterDecoder,
)
from app.operations.infrastructure.maintenance_queue.keys import (
    dead_letter_lifecycle_key,
)
from app.platform.config.redis_config import MaintenanceQueueConfig
from app.shared.types.redis_types import RedisResponse


class RedisDeadLetterSourceOperations(MaintenanceJobSubmitter):
    """Read and replay the evidence held by dead-letter stream entries."""

    _client: Redis
    _config: MaintenanceQueueConfig

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
        return RedisDeadLetterDecoder.decode_dead_letter_entries(raw)

    async def get_dead_letter(
        self, entry_id: str
    ) -> MaintenanceDeadLetterContext | None:
        """Read one exact DLQ entry, its original job, and source request.

        Args:
            entry_id: Exact dead-letter stream entry identifier.

        Returns:
            Dead-letter entry context with original job and source request, or
            None when the entry is absent.
        """
        letter_raw = await self._range_entry(
            self._config.dead_letter_stream_name,
            entry_id,
        )
        letters = RedisDeadLetterDecoder.decode_dead_letter_entries(letter_raw)
        if not letters:
            return None
        entry = letters[0]
        try:
            lifecycle_raw = await cast(
                Awaitable[RedisResponse],
                self._client.get(dead_letter_lifecycle_key(self._config, entry_id)),
            )
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter lifecycle lookup failed"
            ) from exc
        lifecycle = (
            strict_text_response(lifecycle_raw)
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
            source_request = RedisDeadLetterDecoder.decode_dead_letter_source_request(
                source_raw
            )
        except MaintenanceQueueUnavailableError:
            # Redis read succeeded but the retained source shape is corrupt;
            # callers must classify it as unknown/non-retryable evidence.
            source_request = None
        return MaintenanceDeadLetterContext(
            entry=entry,
            original_job=original_job,
            source_request=source_request,
        )

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
        letters = RedisDeadLetterDecoder.decode_dead_letter_entries(letter_raw)
        if not letters:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        letter = letters[0]
        source_raw = await self._range_entry(
            self._config.stream_name,
            letter.source_stream_id,
        )
        request = RedisDeadLetterDecoder.decode_dead_letter_source_request(source_raw)
        if request is None:
            raise MaintenanceDeadLetterSourceGoneError(
                "dead-letter source entry is no longer available for replay"
            )
        return await self.enqueue(request)

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


def strict_text_response(value: RedisResponse) -> str:
    """Decode a lifecycle value as UTF-8 text without scalar coercion.

    Args:
        value: Raw Redis reply for one lifecycle key.

    Returns:
        The decoded text lifecycle value.

    Raises:
        MaintenanceQueueUnavailableError: When Redis returns another shape.
        UnicodeDecodeError: When a byte reply is not valid UTF-8.
    """
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise MaintenanceQueueUnavailableError("Redis dead-letter lifecycle is invalid")
