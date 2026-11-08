"""Mutation-owned Redis dead-letter lifecycle operations."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.operations.application.maintenance_job_queue import (
    MaintenanceDeadLetterLifecycleConflictError,
    MaintenanceDeadLetterNotFoundError,
    MaintenanceDeadLetterSourceGoneError,
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterContext,
    MaintenanceJobSnapshot,
)
from app.operations.infrastructure.maintenance_codec.scalars import (
    RedisValueDecoder,
)
from app.operations.infrastructure.maintenance_codec.streams import (
    RedisDeadLetterDecoder,
)
from app.operations.infrastructure.maintenance_queue.keys import (
    dead_letter_lifecycle_key,
    status_key,
)
from app.operations.infrastructure.maintenance_queue.queue_enums import (
    DeadLetterTransitionReply,
)
from app.operations.infrastructure.redis_maintenance_job_scripts import (
    FINALIZE_MAINTENANCE_DEAD_LETTER_SCRIPT,
    RESERVE_MAINTENANCE_DEAD_LETTER_SCRIPT,
    RETRY_MAINTENANCE_DEAD_LETTER_SCRIPT,
)
from app.platform.config.redis_config import MaintenanceQueueConfig
from app.shared.types.redis_types import RedisResponse


class RedisDeadLetterMutationOperations(MaintenanceJobSubmitter):
    """Apply existing Redis dead-letter purge, retry and retirement transitions."""

    _client: Redis
    _config: MaintenanceQueueConfig

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
        return RedisValueDecoder.integer(length_raw, "dead-letter length")

    async def retry_dead_letter(
        self, entry_id: str, reason: str
    ) -> MaintenanceJobSnapshot:
        """Requeue one terminal job under its original identity through Lua CAS.

        Args:
            entry_id: Dead-letter stream entry identifier to retry.
            reason: Non-blank operator or reconciliation justification.

        Returns:
            Updated job snapshot after same-ID re-enqueue.
        """
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
                status_key(self._config, context.entry.job_id),
                self._config.stream_name,
                self._config.dead_letter_stream_name,
                dead_letter_lifecycle_key(self._config, entry_id),
                entry_id,
                self._config.max_stream_length,
                bounded_reason,
                datetime.now(UTC).isoformat(),
                self._config.consumer_group,
            )
            raw = await cast(Awaitable[RedisResponse], operation)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter retry transition failed"
            ) from exc
        state, job_id, detail = RedisDeadLetterDecoder.decode_dead_letter_transition(
            raw
        )
        if state == DeadLetterTransitionReply.NOT_FOUND.value:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        if state == DeadLetterTransitionReply.CONFLICT.value:
            raise MaintenanceDeadLetterLifecycleConflictError(
                f"dead-letter retry lifecycle conflict: {detail or job_id}"
            )
        if (
            state
            not in {
                DeadLetterTransitionReply.QUEUED.value,
                DeadLetterTransitionReply.IDEMPOTENT.value,
            }
            or not job_id
        ):
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
        """Reserve one failed entry before PostgreSQL provenance archival.

        Args:
            entry_id: Dead-letter stream entry identifier to reserve.

        Returns:
            Dead-letter context updated with the reserved lifecycle state.
        """
        context = await self.get_dead_letter(entry_id)
        if context is None:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        try:
            operation = self._client.eval(
                RESERVE_MAINTENANCE_DEAD_LETTER_SCRIPT,
                4,
                status_key(self._config, context.entry.job_id),
                self._config.dead_letter_stream_name,
                dead_letter_lifecycle_key(self._config, entry_id),
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
        state, _value, detail = RedisDeadLetterDecoder.decode_dead_letter_transition(
            raw
        )
        if state == DeadLetterTransitionReply.NOT_FOUND.value:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        if state not in {
            DeadLetterTransitionReply.RETIRING.value,
            DeadLetterTransitionReply.RETIRED.value,
        }:
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
        """Delete exactly one reserved DLQ/source pair and seal RETIRED state.

        Args:
            entry_id: Reserved dead-letter stream entry identifier.
            source_stream_id: Original stream entry identifier paired with the DLQ entry.
            job_id: Optional retained job identifier when known by the caller.

        Returns:
            True once the DLQ/source pair is removed and marked RETIRED.
        """
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
                status_key(self._config, resolved_job_id),
                self._config.dead_letter_stream_name,
                self._config.stream_name,
                dead_letter_lifecycle_key(self._config, entry_id),
                entry_id,
                source_stream_id,
            )
            raw = await cast(Awaitable[RedisResponse], operation)
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter retirement cleanup failed"
            ) from exc
        state, _removed_dlq, _removed_source = (
            RedisDeadLetterDecoder.decode_dead_letter_transition(raw)
        )
        if (
            state == DeadLetterTransitionReply.ALREADY_RETIRED.value
            or state == DeadLetterTransitionReply.RETIRED.value
        ):
            return True
        if state == DeadLetterTransitionReply.CONFLICT.value:
            raise MaintenanceDeadLetterLifecycleConflictError(
                "dead-letter retirement cleanup lost its lifecycle reservation"
            )
        raise MaintenanceQueueUnavailableError(
            "Redis dead-letter retirement cleanup returned an invalid state"
        )
