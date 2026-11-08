"""Redis Streams adapter for fenced maintenance execution and recovery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.operations.application.maintenance_job_queue import (
    MaintenanceJobConsumer,
    MaintenanceJobDelivery,
    MaintenanceJobNotAdmitted,
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    BatchNoteWriteJobResult,
    EmbeddingReindexJobResult,
)
from app.operations.domain.event_enum.maintenance_job_enums import MaintenanceJobStatus
from app.operations.infrastructure.maintenance_codec.history import (
    MaintenanceAttemptHistoryCodec,
)
from app.operations.infrastructure.maintenance_codec.results import (
    MaintenanceResultCodec,
)
from app.operations.infrastructure.maintenance_codec.scalars import RedisValueDecoder
from app.operations.infrastructure.maintenance_codec.streams import (
    RedisMaintenanceStreamDecoder,
)
from app.operations.infrastructure.maintenance_consumer.consumer_enums import (
    MaintenanceTransitionMode,
    MaintenanceTransitionReply,
)
from app.operations.infrastructure.maintenance_consumer.delivery import (
    MaintenanceDeliveryReader,
)
from app.operations.infrastructure.maintenance_consumer.policy import (
    CONSUMER_LOGGER_NAME,
    MaintenanceConsumerSnapshotPolicy,
    MaintenanceDeliveryLogFields,
    history_after,
)
from app.operations.infrastructure.maintenance_consumer.readback import (
    MaintenanceExecutionReadback,
)
from app.operations.infrastructure.maintenance_consumer.responses import (
    MaintenanceConsumerResponseDecoder,
)
from app.operations.infrastructure.maintenance_consumer.transitions import (
    MaintenanceTransitionExecutor,
)
from app.operations.infrastructure.redis_maintenance_job_queue import (
    RedisMaintenanceJobSubmitter,
)
from app.platform.config.redis_config import MaintenanceQueueConfig
from app.shared.types.redis_types import RedisResponse

logger = logging.getLogger(CONSUMER_LOGGER_NAME)


class RedisMaintenanceJobConsumer(MaintenanceJobConsumer):
    """Worker-facing Redis adapter for claim, fenced transitions, and ACK repair."""

    def __init__(
        self,
        client: Redis,
        config: MaintenanceQueueConfig,
        submitter: RedisMaintenanceJobSubmitter,
    ) -> None:
        """Initialize the worker-facing Redis adapter.

        Args:
            client: Redis client used for Streams and atomic transitions.
            config: Typed maintenance queue settings.
            submitter: Existing adapter for authoritative status reads.
        """
        self._client = client
        self._config = config
        self._submitter = submitter
        self._delivery_reader = MaintenanceDeliveryReader(client, config, submitter)
        self._transitions = MaintenanceTransitionExecutor(client, config)
        self._readback = MaintenanceExecutionReadback(submitter)

    async def ensure_consumer_group(self) -> None:
        """Create the stream and consumer group idempotently."""
        await self._submitter.ensure_consumer_group()

    async def receive(self, consumer_name: str) -> MaintenanceJobDelivery | None:
        """Claim one bounded stale page, then fall through to fresh work.

        Args:
            consumer_name: Unique Redis Streams consumer name for this loop.

        Returns:
            One delivery with readable status evidence, or None when no work is
            available. Missing or corrupt status remains pending and is not rebuilt.
        """
        await self.ensure_consumer_group()
        try:
            claimed = await self._delivery_reader.claim_stale(consumer_name)
            if claimed is not None:
                delivery = await self._delivery_reader.delivery_for(
                    claimed.stream_id, claimed.job_id
                )
                if (
                    delivery is not None
                    and delivery.job.stream_id == delivery.stream_id
                    and (delivery.job.status is not MaintenanceJobStatus.RUNNING)
                    and MaintenanceConsumerSnapshotPolicy.snapshot_consistent_for_admission(
                        delivery.job
                    )
                ):
                    return delivery
            fresh = await cast(
                Awaitable[RedisResponse],
                self._client.xreadgroup(
                    groupname=self._config.consumer_group,
                    consumername=consumer_name,
                    streams={self._config.stream_name: ">"},
                    count=1,
                    block=self._config.block_milliseconds,
                ),
            )
        except RedisError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance receive failed"
            ) from exc
        decoded = RedisMaintenanceStreamDecoder.decode_readgroup_delivery(fresh)
        if decoded is None:
            return None
        return await self._delivery_reader.delivery_for(
            decoded.stream_id, decoded.job_id
        )

    async def mark_running(
        self, delivery: MaintenanceJobDelivery
    ) -> int | MaintenanceJobNotAdmitted:
        """Atomically admit only the current queued/retrying generation.

        Args:
            delivery: Claimed maintenance job and source stream identifier.

        Returns:
            The persisted one-based attempt, or a typed non-admission outcome.
        """
        job = delivery.job
        if not MaintenanceConsumerSnapshotPolicy.snapshot_consistent_for_admission(job):
            return MaintenanceJobNotAdmitted()
        now = datetime.now(UTC)
        new_history = history_after(
            job.attempt_history,
            job.attempts + 1,
            MaintenanceJobStatus.RUNNING.value,
            now,
        )
        try:
            raw = await self._transitions.eval_transition(
                MaintenanceTransitionMode.ADMIT.value,
                delivery,
                job,
                expected_status=job.status.value,
                expected_attempt=job.attempts,
                expected_history=MaintenanceAttemptHistoryCodec.encode_attempt_history(
                    job.attempt_history
                ),
                expected_result=MaintenanceResultCodec.encode_result(job.result),
                occurred_at=now,
                next_history=new_history,
            )
            state, detail = MaintenanceConsumerResponseDecoder.transition_response(raw)
            if state == MaintenanceTransitionReply.ADMITTED.value:
                attempt = RedisValueDecoder.integer(detail, "admitted attempt")
                if attempt == job.attempts + 1:
                    return attempt
                return MaintenanceJobNotAdmitted()
            if state in {
                MaintenanceTransitionReply.REPLAYED_SUCCEEDED.value,
                MaintenanceTransitionReply.REPAIRED_FAILED.value,
            }:
                return MaintenanceJobNotAdmitted(acknowledgement_repaired=True)
            return MaintenanceJobNotAdmitted()
        except (RedisError, MaintenanceQueueUnavailableError) as exc:
            await self._readback.best_effort_status_readback(delivery)
            logger.warning(
                "maintenance job admission response was unresolved; effects were not run",
                extra=MaintenanceDeliveryLogFields(
                    job_id=job.job_id, stream_id=delivery.stream_id
                ),
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return MaintenanceJobNotAdmitted()

    async def mark_succeeded(
        self,
        delivery: MaintenanceJobDelivery,
        attempt: int,
        result: EmbeddingReindexJobResult | BatchNoteWriteJobResult,
    ) -> bool:
        """Publish success only for the admitted generation and attempt.

        Args:
            delivery: Claimed maintenance job and source stream identifier.
            attempt: Actual one-based attempt returned by admission.
            result: Bounded kind-specific result to persist.

        Returns:
            Whether this attempt durably published success and repaired its ACK.
        """
        snapshot = await self._readback.current_running_snapshot(delivery, attempt)
        if snapshot is None:
            return False
        now = datetime.now(UTC)
        history = history_after(
            snapshot.attempt_history, attempt, MaintenanceJobStatus.SUCCEEDED.value, now
        )
        result_json = MaintenanceResultCodec.encode_result(result)
        try:
            raw = await self._transitions.eval_transition(
                MaintenanceTransitionMode.SUCCEEDED.value,
                delivery,
                snapshot,
                expected_status=MaintenanceJobStatus.RUNNING.value,
                expected_attempt=attempt,
                expected_history=MaintenanceAttemptHistoryCodec.encode_attempt_history(
                    snapshot.attempt_history
                ),
                expected_result=b"",
                occurred_at=now,
                next_history=history,
                result_json=result_json,
            )
            state, _detail = MaintenanceConsumerResponseDecoder.transition_response(raw)
            return state == MaintenanceTransitionReply.PUBLISHED_SUCCEEDED.value
        except (RedisError, MaintenanceQueueUnavailableError) as exc:
            return await self._readback.resolve_success_response_loss(
                delivery, attempt, result, exc, admission_owner=self
            )

    async def mark_failed(
        self, delivery: MaintenanceJobDelivery, attempt: int, error_summary: str
    ) -> bool | None:
        """Publish retry or terminal failure under the admitted attempt fence.

        Args:
            delivery: Claimed maintenance job and source stream identifier.
            attempt: Actual one-based attempt returned by admission.
            error_summary: Bounded operator-safe failure summary.

        Returns:
            True when terminal, False when retryable, or None when fenced out.
        """
        snapshot = await self._readback.current_running_snapshot(delivery, attempt)
        if snapshot is None:
            return None
        bounded_error = error_summary[:1000]
        now = datetime.now(UTC)
        history = history_after(
            snapshot.attempt_history,
            attempt,
            MaintenanceJobStatus.FAILED.value
            if attempt >= self._config.max_attempts
            else MaintenanceJobStatus.RETRYING.value,
            now,
            bounded_error,
        )
        try:
            raw = await self._transitions.eval_transition(
                MaintenanceTransitionMode.FAILED.value,
                delivery,
                snapshot,
                expected_status=MaintenanceJobStatus.RUNNING.value,
                expected_attempt=attempt,
                expected_history=MaintenanceAttemptHistoryCodec.encode_attempt_history(
                    snapshot.attempt_history
                ),
                expected_result=b"",
                occurred_at=now,
                next_history=history,
                error_summary=bounded_error,
            )
            state, _detail = MaintenanceConsumerResponseDecoder.transition_response(raw)
            if state == MaintenanceTransitionReply.PUBLISHED_RETRYING.value:
                return False
            if state == MaintenanceTransitionReply.PUBLISHED_FAILED.value:
                return True
            return None
        except (RedisError, MaintenanceQueueUnavailableError) as exc:
            return await self._readback.resolve_failure_response_loss(
                delivery, attempt, bounded_error, exc, admission_owner=self
            )
