"""Maintenance queue contracts independent of Redis implementation details."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.operations.domain.entities.maintenance_job import (
    BatchNoteWriteJobResult,
    EmbeddingReindexJobResult,
    MaintenanceDeadLetterContext,
    MaintenanceDeadLetterEntry,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
    MaintenanceQueueSnapshot,
)


class MaintenanceQueueUnavailableError(RuntimeError):
    """Raised when Redis queueing is disabled or unavailable."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceJobNotAdmitted:
    """Typed rejection of execution admission for one Streams delivery."""

    acknowledgement_repaired: bool = False


class MaintenanceSubmissionRateLimitError(RuntimeError):
    """Raised when a caller exceeds the configured submission budget."""

    def __init__(self, retry_after_seconds: int) -> None:
        """Initialize the explicit retry delay.

        Args:
            retry_after_seconds: Retry after seconds used by this operation.
        """
        super().__init__("maintenance submission rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class MaintenanceDeadLetterNotFoundError(RuntimeError):
    """Raised when a dead-letter entry identifier does not exist."""


class MaintenanceDeadLetterSourceGoneError(RuntimeError):
    """Raised when the source stream entry behind a dead letter was trimmed."""


class MaintenanceDeadLetterLifecycleConflictError(RuntimeError):
    """Raised when a retry or retirement loses the per-entry lifecycle CAS."""


class MaintenanceDeadLetterNotRetryableError(RuntimeError):
    """Raised when evidence does not permit a same-ID retry."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MaintenanceJobDelivery:
    """One Redis Streams delivery awaiting acknowledgement."""

    stream_id: str
    job: MaintenanceJobSnapshot


class MaintenanceJobSubmitter(ABC):
    """API-facing maintenance queue operations."""

    @abstractmethod
    async def ensure_consumer_group(self) -> None:
        """Create the Redis stream and consumer group idempotently."""

    @abstractmethod
    async def enqueue(self, request: MaintenanceJobRequest) -> MaintenanceJobSnapshot:
        """Submit one rate-limited and deduplicated maintenance job.

        Args:
            request: Validated immutable maintenance job submission.

        Returns:
            Immutable queued or deduplicated maintenance job snapshot.
        """

    @abstractmethod
    async def get(self, job_id: str) -> MaintenanceJobSnapshot | None:
        """Read one job snapshot by identifier.

        Args:
            job_id: Maintenance job identifier.

        Returns:
            Immutable job snapshot, or None when the identifier is unknown.
        """

    @abstractmethod
    async def queue_status(self) -> MaintenanceQueueSnapshot:
        """Read bounded backlog and consumer evidence.

        Returns:
            Aggregate maintenance queue snapshot.
        """

    async def get_many(
        self, job_ids: tuple[str, ...]
    ) -> tuple[MaintenanceJobSnapshot | None, ...]:
        """Read a bounded batch in request order without spawning queue work.

        Args:
            job_ids: Between one and fifty existing job identifiers.

        Returns:
            Snapshots in request order; absent or expired identities remain None.

        Raises:
            ValueError: When the batch is empty or exceeds its bound.
            MaintenanceQueueUnavailableError: When an underlying read fails.
        """
        if not 1 <= len(job_ids) <= 50:
            raise ValueError("maintenance batch requires 1..50 job IDs")
        return tuple([await self.get(job_id) for job_id in job_ids])

    @abstractmethod
    async def list_dead_letters(
        self, limit: int
    ) -> tuple[MaintenanceDeadLetterEntry, ...]:
        """Read the newest dead-letter entries without mutating the stream.

        Args:
            limit: Maximum number of entries to return, bounded by the caller.

        Returns:
            Newest-first dead-letter entries.
        """

    @abstractmethod
    async def purge_dead_letters(self) -> int:
        """Drop every dead-letter entry and report how many were removed.

        Returns:
            Number of entries present before the purge.
        """

    @abstractmethod
    async def replay_dead_letter(self, entry_id: str) -> MaintenanceJobSnapshot:
        """Re-enqueue the request behind one dead-letter entry as a new job.

        Args:
            entry_id: Dead-letter stream entry identifier.

        Returns:
            Freshly queued replacement job snapshot.
        """

    async def get_dead_letter(
        self, entry_id: str
    ) -> MaintenanceDeadLetterContext | None:
        """Read one exact dead-letter entry and its retained source evidence.

        Concrete Redis implementations provide this operation. Keeping the
        default explicit preserves the older submitter seam for callers that
        only submit or poll jobs.
        """
        raise NotImplementedError("dead-letter inspection is not supported")

    async def retry_dead_letter(
        self, entry_id: str, reason: str
    ) -> MaintenanceJobSnapshot:
        """Requeue the original job identity after a lifecycle CAS."""
        raise NotImplementedError("dead-letter retry is not supported")

    async def reserve_dead_letter_retirement(
        self, entry_id: str
    ) -> MaintenanceDeadLetterContext:
        """Reserve one entry for archive-before-delete retirement."""
        raise NotImplementedError("dead-letter retirement is not supported")

    async def finalize_dead_letter_retirement(
        self, entry_id: str, source_stream_id: str, job_id: str | None = None
    ) -> bool:
        """Delete only the reserved DLQ/source entries after archive commit."""
        raise NotImplementedError("dead-letter retirement is not supported")


class MaintenanceJobConsumer(ABC):
    """Worker-facing Redis Streams operations."""

    @abstractmethod
    async def ensure_consumer_group(self) -> None:
        """Create the Redis stream and consumer group idempotently."""

    @abstractmethod
    async def receive(self, consumer_name: str) -> MaintenanceJobDelivery | None:
        """Claim one retry-eligible or newly submitted job.

        Args:
            consumer_name: Unique Redis Streams consumer name for this worker loop.

        Returns:
            Claimed job delivery, or None when no work is available.
        """

    @abstractmethod
    async def mark_running(
        self,
        delivery: MaintenanceJobDelivery,
    ) -> int | MaintenanceJobNotAdmitted:
        """Atomically admit a delivery or return its typed rejection.

        Args:
            delivery: Claimed maintenance job and Redis stream identifier.

        Returns:
            Persisted one-based attempt number, or a non-admission outcome.
        """

    @abstractmethod
    async def mark_succeeded(
        self,
        delivery: MaintenanceJobDelivery,
        attempt: int,
        result: EmbeddingReindexJobResult | BatchNoteWriteJobResult,
    ) -> bool:
        """Persist success under the admitted attempt fence and acknowledge.

        Args:
            delivery: Claimed maintenance job and Redis stream identifier.
            attempt: Actual one-based attempt returned by admission.
            result: Bounded kind-specific result to persist.

        Returns:
            Whether this attempt published the success outcome.
        """

    @abstractmethod
    async def mark_failed(
        self,
        delivery: MaintenanceJobDelivery,
        attempt: int,
        error_summary: str,
    ) -> bool | None:
        """Persist retry or terminal failure under the admitted attempt fence.

        Args:
            delivery: Claimed maintenance job and Redis stream identifier.
            attempt: Current one-based execution attempt number.
            error_summary: Bounded operator-safe failure summary.

        Returns:
            True when terminal, False when retryable, or None when fenced out.
        """
