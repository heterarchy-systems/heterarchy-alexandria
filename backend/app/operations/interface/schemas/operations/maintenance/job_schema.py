"""HTTP schemas for Redis-backed maintenance jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints

from app.operations.domain.entities.maintenance_job import (
    BatchNoteWriteJobItem,
    BatchNoteWriteJobResult,
    EmbeddingReindexJobResult,
    MaintenanceJobSnapshot,
    MaintenanceQueueSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.types.extra_types import JSONValue


class MaintenanceJobsRequest(StrictSchemaModel):
    """Bounded batch lookup over existing maintenance job identities."""

    job_ids: Annotated[
        list[
            Annotated[
                str,
                StringConstraints(
                    strict=True, strip_whitespace=True, min_length=1, max_length=128
                ),
            ]
        ],
        Field(
            description="Job IDs to read in request order.", min_length=1, max_length=50
        ),
    ]


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
        Field(description="Requested by for this embedding reindex job request."),
    ] = "manual"
    source_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=200),
        Field(description="Source identifier for this embedding reindex job request."),
    ] = "manual"
    limit: Annotated[
        int,
        Field(
            description="Limit for this embedding reindex job request.", ge=1, le=1000
        ),
    ] = 250
    force: Annotated[
        bool, Field(description="Force for this embedding reindex job request.")
    ] = False


class EmbeddingReindexJobResultResponse(StrictSchemaModel):
    """Bounded embedding batch result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scanned: Annotated[
        int,
        Field(description="Scanned for this embedding reindex job result response."),
    ]
    updated: Annotated[
        int,
        Field(description="Updated for this embedding reindex job result response."),
    ]
    skipped: Annotated[
        int,
        Field(description="Skipped for this embedding reindex job result response."),
    ]
    warnings: Annotated[
        tuple[str, ...],
        Field(description="Warnings for this embedding reindex job result response."),
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
        str, Field(description="Job identifier for this maintenance job response.")
    ]
    kind: Annotated[
        MaintenanceJobKind, Field(description="Kind for this maintenance job response.")
    ]
    status: Annotated[
        MaintenanceJobStatus,
        Field(description="Status for this maintenance job response."),
    ]
    requested_by: Annotated[
        str, Field(description="Requested by for this maintenance job response.")
    ]
    source_id: Annotated[
        str, Field(description="Source identifier for this maintenance job response.")
    ]
    limit: Annotated[int, Field(description="Limit for this maintenance job response.")]
    force: Annotated[
        bool, Field(description="Force for this maintenance job response.")
    ]
    attempts: Annotated[
        int, Field(description="Attempts for this maintenance job response.")
    ]
    submitted_at: Annotated[
        datetime, Field(description="Submitted at for this maintenance job response.")
    ]
    started_at: Annotated[
        datetime | None,
        Field(description="Started at for this maintenance job response."),
    ] = None
    finished_at: Annotated[
        datetime | None,
        Field(description="Finished at for this maintenance job response."),
    ] = None
    stream_id: Annotated[
        str | None,
        Field(description="Stream identifier for this maintenance job response."),
    ] = None
    deduplicated: Annotated[
        bool, Field(description="Deduplicated for this maintenance job response.")
    ] = False
    error_summary: Annotated[
        str | None,
        Field(description="Error summary for this maintenance job response."),
    ] = None
    result: Annotated[
        EmbeddingReindexJobResultResponse | BatchNoteWriteJobResultResponse | None,
        Field(description="Result for this maintenance job response."),
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
        Field(description="Requested by for this batch note write job request."),
    ] = "manual"
    operations: Annotated[
        list[dict[str, JSONValue]],
        Field(min_length=1, max_length=50),
        Field(
            description="JSON write operations executed asynchronously by the worker."
        ),
    ]


class BatchNoteWriteJobItemResponse(StrictSchemaModel):
    """One per-item CAS outcome inside an async batch note write job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Annotated[str, Field(description="Path for this batch job item.")]
    status: Annotated[str, Field(description="Status for this batch job item.")]
    content_hash: Annotated[
        str | None, Field(description="Content hash for this batch job item.")
    ] = None
    current_content_hash: Annotated[
        str | None,
        Field(description="Current content hash for this batch job item."),
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
        int, Field(description="Succeeded for this batch job result response.")
    ]
    conflicted: Annotated[
        int, Field(description="Conflicted for this batch job result response.")
    ]
    failed: Annotated[
        int, Field(description="Failed for this batch job result response.")
    ]
    items: Annotated[
        list[BatchNoteWriteJobItemResponse],
        Field(description="Items for this batch job result response."),
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


class MaintenanceJobsResponse(StrictSchemaModel):
    """Batch progress, with absent snapshots distinguished from failed jobs."""

    jobs: Annotated[
        list[MaintenanceJobResponse], Field(description="Known jobs in request order.")
    ]
    missing_job_ids: Annotated[
        list[str], Field(description="Unknown or expired job identities.")
    ]


class MaintenanceQueueStatusResponse(StrictSchemaModel):
    """Bounded Redis Streams backlog and worker evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stream_length: Annotated[
        int,
        Field(description="Stream length for this maintenance queue status response."),
    ]
    pending: Annotated[
        int, Field(description="Pending for this maintenance queue status response.")
    ]
    consumers: Annotated[
        int, Field(description="Consumers for this maintenance queue status response.")
    ]
    dead_letter_length: Annotated[
        int,
        Field(
            description="Dead letter length for this maintenance queue status response."
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
