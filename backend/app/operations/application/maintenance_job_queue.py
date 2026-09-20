"""Maintenance queue contracts independent of Redis implementation details."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.operations.domain.entities.maintenance_job import (
    EmbeddingReindexJobResult,
    MaintenanceDeadLetterEntry,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
    MaintenanceQueueSnapshot,
)


class MaintenanceQueueUnavailableError(RuntimeError):
    """Raised when Redis queueing is disabled or unavailable."""


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
    async def mark_running(self, delivery: MaintenanceJobDelivery) -> int:
        """Mark a delivery running and return its attempt number.

        Args:
            delivery: Claimed maintenance job and Redis stream identifier.

        Returns:
            Persisted one-based execution attempt number.
        """

    @abstractmethod
    async def mark_succeeded(
        self,
        delivery: MaintenanceJobDelivery,
        result: EmbeddingReindexJobResult,
    ) -> None:
        """Persist success and acknowledge the stream entry.

        Args:
            delivery: Claimed maintenance job and Redis stream identifier.
            result: Bounded embedding reindex result to persist.
        """

    @abstractmethod
    async def mark_failed(
        self,
        delivery: MaintenanceJobDelivery,
        attempt: int,
        error_summary: str,
    ) -> bool:
        """Persist retry or terminal failure and return terminal state.

        Args:
            delivery: Claimed maintenance job and Redis stream identifier.
            attempt: Current one-based execution attempt number.
            error_summary: Bounded operator-safe failure summary.

        Returns:
            True when the job became terminal; False when it remains retryable.
        """
