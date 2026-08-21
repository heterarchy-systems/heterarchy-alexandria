"""HTTP schemas for Redis-backed maintenance jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, StringConstraints

from app.operations.domain.entities.maintenance_job import (
    EmbeddingReindexJobResult,
    MaintenanceJobSnapshot,
    MaintenanceQueueSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


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
        EmbeddingReindexJobResultResponse | None,
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
            result=(
                None
                if result is None
                else EmbeddingReindexJobResultResponse.from_entity(result)
            ),
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
        return cls(
            stream_length=snapshot.stream_length,
            pending=snapshot.pending,
            consumers=snapshot.consumers,
            dead_letter_length=snapshot.dead_letter_length,
        )
