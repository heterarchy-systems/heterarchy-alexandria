"""Redis consumer readback responsibilities."""

from __future__ import annotations

import logging

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
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import MaintenanceJobStatus
from app.operations.infrastructure.maintenance_consumer.policy import (
    CONSUMER_LOGGER_NAME,
    MaintenanceConsumerSnapshotPolicy,
    MaintenanceDeliveryLogFields,
)
from app.operations.infrastructure.redis_maintenance_job_queue import (
    RedisMaintenanceJobSubmitter,
)

logger = logging.getLogger(CONSUMER_LOGGER_NAME)


class MaintenanceExecutionReadback:
    """Resolve uncertain replies from the existing authoritative status reader."""

    def __init__(self, submitter: RedisMaintenanceJobSubmitter) -> None:
        """Initialize the execution readback helper with the status submitter.

        Args:
            submitter: Authoritative Redis maintenance job status reader.
        """
        self._submitter = submitter

    async def current_running_snapshot(
        self, delivery: MaintenanceJobDelivery, attempt: int
    ) -> MaintenanceJobSnapshot | None:
        """Read back current status before preparing a history CAS.

        Args:
            delivery: Claimed stream delivery under execution.
            attempt: Expected running attempt number.

        Returns:
            Matching running snapshot, or None if absent or mismatched.
        """
        snapshot = await self._submitter.get(delivery.job.job_id)
        if snapshot is None:
            return None
        if (
            snapshot.status is not MaintenanceJobStatus.RUNNING
            or snapshot.stream_id != delivery.stream_id
            or snapshot.attempts != attempt
            or (attempt < 1)
            or (snapshot.result is not None)
            or (not snapshot.attempt_history)
            or (
                snapshot.attempt_history[-1].status
                != MaintenanceJobStatus.RUNNING.value
            )
            or (snapshot.attempt_history[-1].attempt < attempt)
        ):
            return None
        return snapshot

    async def resolve_success_response_loss(
        self,
        delivery: MaintenanceJobDelivery,
        attempt: int,
        result: EmbeddingReindexJobResult | BatchNoteWriteJobResult,
        error: RedisError | MaintenanceQueueUnavailableError,
        *,
        admission_owner: MaintenanceJobConsumer,
    ) -> bool:
        """Resolve an unknown completion reply from durable status before ACK repair.

        Args:
            delivery: Claimed stream delivery whose success reply was lost.
            attempt: Attempt number that completed execution.
            result: Expected job execution result payload.
            error: Transport or queue error encountered during transition.
            admission_owner: Consumer admission owner used for ACK repair replay.

        Returns:
            True if durable state confirmed success and ACK repair completed.

        Raises:
            MaintenanceQueueUnavailableError: If status readback itself fails.
        """
        try:
            snapshot = await self._submitter.get(delivery.job.job_id)
        except (RedisError, MaintenanceQueueUnavailableError, ValueError) as read_error:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance success outcome remains unresolved after readback"
            ) from read_error
        if (
            snapshot is None
            or not MaintenanceConsumerSnapshotPolicy.matches_terminal_snapshot(
                snapshot,
                delivery,
                attempt,
                MaintenanceJobStatus.SUCCEEDED,
                result=result,
            )
        ):
            logger.warning(
                "maintenance success response was lost; durable state is not successful",
                extra=MaintenanceDeliveryLogFields(
                    job_id=delivery.job.job_id, stream_id=delivery.stream_id
                ),
                exc_info=(type(error), error, error.__traceback__),
            )
            return False
        replay = await admission_owner.mark_running(
            MaintenanceJobDelivery(stream_id=delivery.stream_id, job=snapshot)
        )
        return (
            isinstance(replay, MaintenanceJobNotAdmitted)
            and replay.acknowledgement_repaired
        )

    async def resolve_failure_response_loss(
        self,
        delivery: MaintenanceJobDelivery,
        attempt: int,
        error_summary: str,
        error: RedisError | MaintenanceQueueUnavailableError,
        *,
        admission_owner: MaintenanceJobConsumer,
    ) -> bool | None:
        """Resolve failure publication from durable state without executing again.

        Args:
            delivery: Claimed stream delivery whose failure reply was lost.
            attempt: Attempt number that failed execution.
            error_summary: Expected failure summary string.
            error: Transport or queue error encountered during transition.
            admission_owner: Consumer admission owner used for ACK repair replay.

        Returns:
            False if retrying, True if terminal failure ACK was repaired, or None if unresolved.

        Raises:
            MaintenanceQueueUnavailableError: If status readback itself fails.
        """
        try:
            snapshot = await self._submitter.get(delivery.job.job_id)
        except (RedisError, MaintenanceQueueUnavailableError, ValueError) as read_error:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance failure outcome remains unresolved after readback"
            ) from read_error
        if (
            snapshot is None
            or not MaintenanceConsumerSnapshotPolicy.matches_failure_snapshot(
                snapshot, delivery, attempt, error_summary
            )
        ):
            logger.warning(
                "maintenance failure response was lost; durable state remains unresolved",
                extra=MaintenanceDeliveryLogFields(
                    job_id=delivery.job.job_id, stream_id=delivery.stream_id
                ),
                exc_info=(type(error), error, error.__traceback__),
            )
            return None
        if snapshot.status is MaintenanceJobStatus.RETRYING:
            return False
        replay = await admission_owner.mark_running(
            MaintenanceJobDelivery(stream_id=delivery.stream_id, job=snapshot)
        )
        if (
            isinstance(replay, MaintenanceJobNotAdmitted)
            and replay.acknowledgement_repaired
        ):
            return True
        return None

    async def best_effort_status_readback(
        self, delivery: MaintenanceJobDelivery
    ) -> None:
        """Read back an uncertain admission without granting execution authority.

        Args:
            delivery: Claimed stream delivery whose admission reply was uncertain.
        """
        try:
            await self._submitter.get(delivery.job.job_id)
        except (RedisError, MaintenanceQueueUnavailableError, ValueError) as exc:
            logger.warning(
                "maintenance admission state could not be read back",
                extra=MaintenanceDeliveryLogFields(
                    job_id=delivery.job.job_id, stream_id=delivery.stream_id
                ),
                exc_info=(type(exc), exc, exc.__traceback__),
            )
