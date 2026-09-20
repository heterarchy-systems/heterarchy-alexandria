"""Async batch note write submission composing staging and the queue."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.operations.application.maintenance_job_queue import (
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
    MaintenanceSubmissionRateLimitError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import MaintenanceJobKind
from app.operations.infrastructure.maintenance_job_payload_store import (
    MaintenanceJobPayloadStore,
)
from app.shared.infrastructure.database import Database
from app.shared.types.extra_types import JSONValue


class MaintenanceBatchWritePayloadTooLargeError(RuntimeError):
    """Raised when an async batch write exceeds the bounded operation limit."""


class MaintenanceBatchNoteWriteService:
    """Stage bounded note write operations and enqueue one queue job.

    Redis Streams job fields carry identifiers only, so the operation
    bodies are staged durably in PostgreSQL and referenced by the job's
    source_id; per-item CAS keeps a retried execution idempotent.
    """

    def __init__(
        self,
        database: Database,
        submitter: MaintenanceJobSubmitter | None,
        max_operations: int = 50,
    ) -> None:
        """Create the submission service.

        Args:
            database: Shared database coordinator for payload staging.
            submitter: Maintenance queue submission port; None disables it.
            max_operations: Upper bound on staged batch size.
        """
        if max_operations <= 0:
            raise ValueError("max_operations must be greater than zero")
        self._database = database
        self._submitter = submitter
        self._max_operations = max_operations

    async def submit(
        self,
        operations: Sequence[dict[str, JSONValue]],
        requested_by: str,
    ) -> MaintenanceJobSnapshot:
        """Stage one bounded batch and enqueue its execution job.

        Args:
            operations: JSON write operations executed by the worker.
            requested_by: Operator or automation identity for the job.

        Returns:
            The queued or deduplicated maintenance job snapshot.

        Raises:
            MaintenanceBatchWritePayloadTooLargeError: When the batch
                exceeds the bounded operation limit.
            MaintenanceQueueUnavailableError: When queueing is disabled
                or unavailable.
        """
        if self._submitter is None:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance queue is disabled"
            )
        if len(operations) > self._max_operations:
            raise MaintenanceBatchWritePayloadTooLargeError(
                f"ASYNC_BATCH_TOO_LARGE: {len(operations)} operations exceeds "
                f"the {self._max_operations} limit"
            )
        batch_id = uuid.uuid4().hex
        async with self._database.request_session() as session:
            await MaintenanceJobPayloadStore(session).save(
                batch_id,
                MaintenanceJobKind.BATCH_NOTE_WRITE.value,
                {"requested_by": requested_by, "operations": list(operations)},
            )
        try:
            return await self._submitter.enqueue(
                MaintenanceJobRequest(
                    kind=MaintenanceJobKind.BATCH_NOTE_WRITE,
                    requested_by=requested_by,
                    source_id=batch_id,
                    limit=len(operations),
                    force=False,
                )
            )
        except (MaintenanceQueueUnavailableError, MaintenanceSubmissionRateLimitError):
            async with self._database.request_session() as session:
                await MaintenanceJobPayloadStore(session).delete(batch_id)
            raise
