"""HTTP schemas for Redis-backed maintenance jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints

from app.operations.domain.entities.maintenance_job import (
    BatchNoteWriteJobItem,
    BatchNoteWriteJobResult,
    EmbeddingReindexJobResult,
    MaintenanceDeadLetterEntry,
    MaintenanceJobSnapshot,
    MaintenanceQueueSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.types.extra_types import JSONValue


class EmbeddingReindexJobRequest(StrictSchemaModel):
    """Submit one bounded embedding reindex operation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    requested_by: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=120),
        described_field("Requested by for this embedding reindex job request."),
    ] = "manual"
    source_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=200),
        described_field("Source identifier for this embedding reindex job request."),
    ] = "manual"
    limit: Annotated[
        int,
        described_field("Limit for this embedding reindex job request.", ge=1, le=1000),
    ] = 250
    force: Annotated[
        bool, described_field("Force for this embedding reindex job request.")
    ] = False


class EmbeddingReindexJobResultResponse(StrictSchemaModel):
    """Bounded embedding batch result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scanned: Annotated[
        int, described_field("Scanned for this embedding reindex job result response.")
    ]
    updated: Annotated[
        int, described_field("Updated for this embedding reindex job result response.")
    ]
    skipped: Annotated[
        int, described_field("Skipped for this embedding reindex job result response.")
    ]
    warnings: Annotated[
        tuple[str, ...],
        described_field("Warnings for this embedding reindex job result response."),
    ] = ()

    @classmethod
    def from_entity(
        cls,
        result: EmbeddingReindexJobResult,
    ) -> EmbeddingReindexJobResultResponse:
        """Build this schema from a domain entity.

        Args:
            result: Operation result to serialize or persist.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(
            scanned=result.scanned,
            updated=result.updated,
            skipped=result.skipped,
            warnings=result.warnings,
        )


class MaintenanceJobResponse(StrictSchemaModel):
    """Operator-visible queued maintenance lifecycle state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: Annotated[
        str, described_field("Job identifier for this maintenance job response.")
    ]
    kind: Annotated[
        MaintenanceJobKind, described_field("Kind for this maintenance job response.")
    ]
    status: Annotated[
        MaintenanceJobStatus,
        described_field("Status for this maintenance job response."),
    ]
    requested_by: Annotated[
        str, described_field("Requested by for this maintenance job response.")
    ]
    source_id: Annotated[
        str, described_field("Source identifier for this maintenance job response.")
    ]
    limit: Annotated[int, described_field("Limit for this maintenance job response.")]
    force: Annotated[bool, described_field("Force for this maintenance job response.")]
    attempts: Annotated[
        int, described_field("Attempts for this maintenance job response.")
    ]
    submitted_at: Annotated[
        datetime, described_field("Submitted at for this maintenance job response.")
    ]
    started_at: Annotated[
        datetime | None,
        described_field("Started at for this maintenance job response."),
    ] = None
    finished_at: Annotated[
        datetime | None,
        described_field("Finished at for this maintenance job response."),
    ] = None
    stream_id: Annotated[
        str | None,
        described_field("Stream identifier for this maintenance job response."),
    ] = None
    deduplicated: Annotated[
        bool, described_field("Deduplicated for this maintenance job response.")
    ] = False
    error_summary: Annotated[
        str | None, described_field("Error summary for this maintenance job response.")
    ] = None
    result: Annotated[
        EmbeddingReindexJobResultResponse | BatchNoteWriteJobResultResponse | None,
        described_field("Result for this maintenance job response."),
    ] = None

    @classmethod
    def from_entity(cls, snapshot: MaintenanceJobSnapshot) -> MaintenanceJobResponse:
        """Map an immutable domain snapshot to the HTTP response.

        Args:
            snapshot: Immutable maintenance job domain snapshot.

        Returns:
            Validated operator-visible maintenance job response model.
        """
        result = snapshot.result
        mapped_result: (
            EmbeddingReindexJobResultResponse | BatchNoteWriteJobResultResponse | None
        )
        if isinstance(result, BatchNoteWriteJobResult):
            mapped_result = BatchNoteWriteJobResultResponse.from_entity(result)
        elif result is None:
            mapped_result = None
        else:
            mapped_result = EmbeddingReindexJobResultResponse.from_entity(result)
        return cls(
            job_id=snapshot.job_id,
            kind=snapshot.kind,
            status=snapshot.status,
            requested_by=snapshot.requested_by,
            source_id=snapshot.source_id,
            limit=snapshot.limit,
            force=snapshot.force,
            attempts=snapshot.attempts,
            submitted_at=snapshot.submitted_at,
            started_at=snapshot.started_at,
            finished_at=snapshot.finished_at,
            stream_id=snapshot.stream_id,
            deduplicated=snapshot.deduplicated,
            error_summary=snapshot.error_summary,
            result=mapped_result,
        )


class BatchNoteWriteJobRequest(StrictSchemaModel):
    """Submit one bounded asynchronous batch note write."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    requested_by: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=120),
        described_field("Requested by for this batch note write job request."),
    ] = "manual"
    operations: Annotated[
        list[dict[str, JSONValue]],
        Field(min_length=1, max_length=50),
        described_field("JSON write operations executed asynchronously by the worker."),
    ]


class BatchNoteWriteJobItemResponse(StrictSchemaModel):
    """One per-item CAS outcome inside an async batch note write job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Annotated[str, described_field("Path for this batch job item.")]
    status: Annotated[str, described_field("Status for this batch job item.")]
    content_hash: Annotated[
        str | None, described_field("Content hash for this batch job item.")
    ] = None
    current_content_hash: Annotated[
        str | None,
        described_field("Current content hash for this batch job item."),
    ] = None

    @classmethod
    def from_entity(cls, item: BatchNoteWriteJobItem) -> BatchNoteWriteJobItemResponse:
        """Map an immutable job item to the HTTP response.

        Args:
            item: Immutable batch job item.

        Returns:
            Validated batch job item response model.
        """
        return cls(
            path=item.path,
            status=item.status,
            content_hash=item.content_hash,
            current_content_hash=item.current_content_hash,
        )


class BatchNoteWriteJobResultResponse(StrictSchemaModel):
    """Bounded per-item outcome of one async batch note write job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    succeeded: Annotated[
        int, described_field("Succeeded for this batch job result response.")
    ]
    conflicted: Annotated[
        int, described_field("Conflicted for this batch job result response.")
    ]
    failed: Annotated[
        int, described_field("Failed for this batch job result response.")
    ]
    items: Annotated[
        list[BatchNoteWriteJobItemResponse],
        described_field("Items for this batch job result response."),
    ] = Field(default_factory=list)

    @classmethod
    def from_entity(
        cls, result: BatchNoteWriteJobResult
    ) -> BatchNoteWriteJobResultResponse:
        """Map an immutable job result to the HTTP response.

        Args:
            result: Immutable batch note write job result.

        Returns:
            Validated batch job result response model.
        """
        return cls(
            succeeded=result.succeeded,
            conflicted=result.conflicted,
            failed=result.failed,
            items=[
                BatchNoteWriteJobItemResponse.from_entity(item) for item in result.items
            ],
        )


class MaintenanceQueueStatusResponse(StrictSchemaModel):
    """Bounded Redis Streams backlog and worker evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stream_length: Annotated[
        int,
        described_field("Stream length for this maintenance queue status response."),
    ]
    pending: Annotated[
        int, described_field("Pending for this maintenance queue status response.")
    ]
    consumers: Annotated[
        int, described_field("Consumers for this maintenance queue status response.")
    ]
    dead_letter_length: Annotated[
        int,
        described_field(
            "Dead letter length for this maintenance queue status response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        snapshot: MaintenanceQueueSnapshot,
    ) -> MaintenanceQueueStatusResponse:
        """Build this schema from a domain entity.

        Args:
            snapshot: Operational snapshot to serialize or verify.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(
            stream_length=snapshot.stream_length,
            pending=snapshot.pending,
            consumers=snapshot.consumers,
            dead_letter_length=snapshot.dead_letter_length,
        )


class MaintenanceDeadLetterResponse(StrictSchemaModel):
    """One terminal job failure recorded in the dead-letter stream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: Annotated[
        str,
        described_field("Entry identifier for this dead-letter response."),
    ]
    job_id: Annotated[
        str,
        described_field("Job identifier for this dead-letter response."),
    ]
    kind: Annotated[
        MaintenanceJobKind,
        described_field("Kind for this dead-letter response."),
    ]
    attempts: Annotated[
        int,
        described_field("Attempts for this dead-letter response."),
    ]
    failed_at: Annotated[
        datetime,
        described_field("Failed at for this dead-letter response."),
    ]
    error_summary: Annotated[
        str,
        described_field("Error summary for this dead-letter response."),
    ]
    source_stream_id: Annotated[
        str,
        described_field("Source stream identifier for this dead-letter response."),
    ]

    @classmethod
    def from_entity(
        cls,
        entry: MaintenanceDeadLetterEntry,
    ) -> MaintenanceDeadLetterResponse:
        """Map an immutable dead-letter entry to the HTTP response.

        Args:
            entry: Immutable dead-letter domain entry.

        Returns:
            Validated operator-visible dead-letter response model.
        """
        return cls(
            entry_id=entry.entry_id,
            job_id=entry.job_id,
            kind=entry.kind,
            attempts=entry.attempts,
            failed_at=entry.failed_at,
            error_summary=entry.error_summary,
            source_stream_id=entry.source_stream_id,
        )


class MaintenanceDeadLetterListResponse(StrictSchemaModel):
    """Newest-first bounded dead-letter entries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: Annotated[
        tuple[MaintenanceDeadLetterResponse, ...],
        described_field("Entries for this dead-letter list response."),
    ] = ()


class MaintenanceDeadLetterPurgeResponse(StrictSchemaModel):
    """Result of dropping every dead-letter entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    purged: Annotated[
        int,
        described_field("Purged entry count for this dead-letter purge response."),
    ]
