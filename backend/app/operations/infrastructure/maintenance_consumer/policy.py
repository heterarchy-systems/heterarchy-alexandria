"""Redis consumer policy responsibilities."""

from __future__ import annotations

from datetime import datetime

from typing_extensions import TypedDict

from app.operations.application.maintenance_job_queue import (
    MaintenanceJobDelivery,
)
from app.operations.domain.entities.maintenance_job import (
    BatchNoteWriteJobResult,
    EmbeddingReindexJobResult,
    MaintenanceJobAttempt,
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import MaintenanceJobStatus
from app.operations.infrastructure.maintenance_codec.history import (
    MaintenanceAttemptHistoryCodec,
)

CONSUMER_LOGGER_NAME = "app.operations.infrastructure.redis_maintenance_job_consumer"


class MaintenanceDeliveryLogFields(TypedDict, closed=True):
    """Stable context attached to consumer warning records."""

    job_id: str
    stream_id: str


class MaintenanceConsumerSnapshotPolicy:
    """Judge persisted delivery generations without effects."""

    @staticmethod
    def matches_terminal_snapshot(
        snapshot: MaintenanceJobSnapshot,
        delivery: MaintenanceJobDelivery,
        attempt: int,
        status: MaintenanceJobStatus,
        *,
        result: EmbeddingReindexJobResult | BatchNoteWriteJobResult | None = None,
        error_summary: str | None = None,
    ) -> bool:
        """Check a durable terminal readback against the exact delivery generation.

        Args:
            snapshot: Persisted maintenance job snapshot read from Redis.
            delivery: Claimed stream delivery under verification.
            attempt: Attempt number expected on the terminal snapshot.
            status: Expected terminal job status.
            result: Optional expected job result payload.
            error_summary: Optional expected failure summary string.

        Returns:
            True if the persisted snapshot matches the exact terminal delivery generation.
        """
        if (
            snapshot.status is not status
            or snapshot.stream_id != delivery.stream_id
            or snapshot.attempts != attempt
            or (not snapshot.attempt_history)
            or (snapshot.attempt_history[-1].status != status.value)
            or (snapshot.attempt_history[-1].attempt < attempt)
        ):
            return False
        if result is not None and snapshot.result != result:
            return False
        return error_summary is None or (
            snapshot.error_summary == error_summary
            and snapshot.attempt_history[-1].error_summary == error_summary
        )

    @staticmethod
    def matches_failure_snapshot(
        snapshot: MaintenanceJobSnapshot,
        delivery: MaintenanceJobDelivery,
        attempt: int,
        error_summary: str,
    ) -> bool:
        """Match a retryable or terminal failure to its committed attempt evidence.

        Args:
            snapshot: Persisted maintenance job snapshot read from Redis.
            delivery: Claimed stream delivery under verification.
            attempt: Attempt number expected on the failure snapshot.
            error_summary: Expected failure summary string.

        Returns:
            True if the persisted snapshot records the expected failure attempt.
        """
        return (
            snapshot.status
            in {MaintenanceJobStatus.RETRYING, MaintenanceJobStatus.FAILED}
            and snapshot.stream_id == delivery.stream_id
            and (snapshot.attempts == attempt)
            and bool(snapshot.attempt_history)
            and (snapshot.attempt_history[-1].attempt >= attempt)
            and (snapshot.attempt_history[-1].status == snapshot.status.value)
            and (snapshot.error_summary == error_summary)
            and (snapshot.attempt_history[-1].error_summary == error_summary)
        )

    @staticmethod
    def snapshot_consistent_for_admission(snapshot: MaintenanceJobSnapshot) -> bool:
        """Reject inconsistent status/history pairs before admission or ACK repair.

        Args:
            snapshot: Persisted maintenance job snapshot to validate.

        Returns:
            True if the snapshot status, timestamps, result, and attempt history are consistent.
        """
        if snapshot.status is MaintenanceJobStatus.QUEUED:
            return (
                snapshot.attempts == 0
                and snapshot.started_at is None
                and (snapshot.finished_at is None)
                and (snapshot.result is None)
                and (snapshot.error_summary is None)
                and (
                    not snapshot.attempt_history
                    or snapshot.attempt_history[-1].status
                    == MaintenanceJobStatus.FAILED.value
                )
            )
        if snapshot.status is MaintenanceJobStatus.RETRYING:
            return (
                snapshot.attempts > 0
                and snapshot.finished_at is None
                and (snapshot.result is None)
                and (snapshot.error_summary is not None)
                and bool(snapshot.attempt_history)
                and (
                    snapshot.attempt_history[-1].status
                    == MaintenanceJobStatus.RETRYING.value
                )
                and (snapshot.attempt_history[-1].attempt >= snapshot.attempts)
                and (
                    snapshot.attempt_history[-1].error_summary == snapshot.error_summary
                )
            )
        if snapshot.status is MaintenanceJobStatus.RUNNING:
            return (
                snapshot.attempts > 0
                and snapshot.started_at is not None
                and (snapshot.finished_at is None)
                and (snapshot.result is None)
                and (snapshot.error_summary is None)
                and bool(snapshot.attempt_history)
                and (
                    snapshot.attempt_history[-1].status
                    == MaintenanceJobStatus.RUNNING.value
                )
                and (snapshot.attempt_history[-1].attempt >= snapshot.attempts)
            )
        if snapshot.status is MaintenanceJobStatus.SUCCEEDED:
            return (
                snapshot.attempts > 0
                and snapshot.started_at is not None
                and (snapshot.finished_at is not None)
                and (snapshot.result is not None)
                and (snapshot.error_summary is None)
                and bool(snapshot.attempt_history)
                and (
                    snapshot.attempt_history[-1].status
                    == MaintenanceJobStatus.SUCCEEDED.value
                )
                and (snapshot.attempt_history[-1].attempt >= snapshot.attempts)
                and (snapshot.attempt_history[-1].error_summary is None)
            )
        if snapshot.status is MaintenanceJobStatus.FAILED:
            return (
                snapshot.attempts > 0
                and snapshot.started_at is not None
                and (snapshot.finished_at is not None)
                and (snapshot.result is None)
                and (snapshot.error_summary is not None)
                and bool(snapshot.attempt_history)
                and (
                    snapshot.attempt_history[-1].status
                    == MaintenanceJobStatus.FAILED.value
                )
                and (snapshot.attempt_history[-1].attempt >= snapshot.attempts)
                and (
                    snapshot.attempt_history[-1].error_summary == snapshot.error_summary
                )
            )
        return False


def history_after(
    history: tuple[MaintenanceJobAttempt, ...],
    attempt: int,
    status: str,
    occurred_at: datetime,
    error_summary: str | None = None,
) -> bytes:
    """Append one bounded event while retaining the existing history numbering.

    Args:
        history: Prior attempt history tuple.
        attempt: Current attempt number.
        status: Status string for the appended attempt event.
        occurred_at: UTC timestamp when the transition occurred.
        error_summary: Optional error summary for failed or retrying attempts.

    Returns:
        UTF-8 JSON-encoded attempt history bytes.
    """
    resolved_attempt = max(attempt, history[-1].attempt if history else 0)
    return MaintenanceAttemptHistoryCodec.encode_attempt_history(
        (
            *history,
            MaintenanceJobAttempt(
                attempt=resolved_attempt,
                status=status,
                occurred_at=occurred_at,
                error_summary=error_summary,
            ),
        )
    )
