"""HTTP schemas for Redis-backed maintenance jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints, field_validator

from app.operations.domain.entities.maintenance_job import (
    BatchNoteWriteJobItem,
    BatchNoteWriteJobResult,
    EmbeddingReindexJobResult,
    MaintenanceDeadLetterEntry,
    MaintenanceDeadLetterInspection,
    MaintenanceDeadLetterReconcileItem,
    MaintenanceDeadLetterReconcileResult,
    MaintenanceDeadLetterRetireResult,
    MaintenanceDeadLetterRetryResult,
    MaintenanceJobAttempt,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
    MaintenanceQueueSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterOutcomeClass,
    MaintenanceDeadLetterRetirementClassification,
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
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
        described_field(
            "Job IDs to read in request order.", min_length=1, max_length=50
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


class MaintenanceJobsResponse(StrictSchemaModel):
    """Batch progress, with absent snapshots distinguished from failed jobs."""

    jobs: Annotated[
        list[MaintenanceJobResponse], described_field("Known jobs in request order.")
    ]
    missing_job_ids: Annotated[
        list[str], described_field("Unknown or expired job identities.")
    ]


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
    lifecycle: Annotated[
        str,
        described_field("Redis lifecycle reservation for this dead-letter response."),
    ] = "ACTIVE"

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
            lifecycle=entry.lifecycle,
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


class MaintenanceDeadLetterSourceRequestResponse(StrictSchemaModel):
    """Original typed request retained in the Redis source stream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Annotated[MaintenanceJobKind, described_field("Original job kind.")]
    requested_by: Annotated[str, described_field("Original requester.")]
    source_id: Annotated[str, described_field("Original stable source identity.")]
    limit: Annotated[int, described_field("Original bounded operation limit.")]
    force: Annotated[bool, described_field("Original force flag.")]

    @classmethod
    def from_entity(
        cls, request: MaintenanceJobRequest
    ) -> MaintenanceDeadLetterSourceRequestResponse:
        """Map the internal source request to the public response."""
        return cls(
            kind=request.kind,
            requested_by=request.requested_by,
            source_id=request.source_id,
            limit=request.limit,
            force=request.force,
        )


class MaintenanceJobAttemptResponse(StrictSchemaModel):
    """One retained worker lifecycle event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt: Annotated[int, described_field("Attempt number.")]
    status: Annotated[str, described_field("Attempt lifecycle status.")]
    occurred_at: Annotated[datetime, described_field("Attempt event time.")]
    error_summary: Annotated[str | None, described_field("Attempt error.")] = None

    @classmethod
    def from_entity(
        cls, attempt: MaintenanceJobAttempt
    ) -> MaintenanceJobAttemptResponse:
        """Map a retained attempt event."""
        return cls(
            attempt=attempt.attempt,
            status=attempt.status,
            occurred_at=attempt.occurred_at,
            error_summary=attempt.error_summary,
        )


class MaintenanceDeadLetterInspectionResponse(StrictSchemaModel):
    """Exact DLQ evidence and an explicit retry recommendation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry: Annotated[
        MaintenanceDeadLetterResponse,
        described_field("Exact dead-letter entry."),
    ]
    original_job: Annotated[
        MaintenanceJobResponse | None,
        described_field("Current original job snapshot."),
    ] = None
    source_request: Annotated[
        MaintenanceDeadLetterSourceRequestResponse | None,
        described_field("Original source request when retained."),
    ] = None
    source_payload: Annotated[
        dict[str, JSONValue] | None,
        described_field("Durable batch payload when available."),
    ] = None
    attempts: Annotated[
        tuple[MaintenanceJobAttemptResponse, ...],
        described_field("Retained attempt history."),
    ] = ()
    error_history: Annotated[
        tuple[str, ...], described_field("Retained error history.")
    ] = ()
    idempotency_keys: Annotated[
        tuple[str, ...], described_field("Stable effect idempotency keys.")
    ] = ()
    effect_identities: Annotated[
        tuple[str, ...], described_field("Stable effect identities.")
    ] = ()
    source_identity: Annotated[str, described_field("Stable source identity.")]
    retryable: Annotated[bool, described_field("Whether same-ID retry is allowed.")]
    outcome_class: Annotated[
        MaintenanceDeadLetterOutcomeClass,
        described_field("Evidence outcome class."),
    ]
    recommended_action: Annotated[str, described_field("Evidence-based next action.")]
    retired: Annotated[bool, described_field("Whether this is archived evidence.")] = (
        False
    )
    archive_id: Annotated[str | None, described_field("Retirement archive ID.")] = None
    retirement_reason: Annotated[str | None, described_field("Retirement reason.")] = (
        None
    )
    retirement_classification: Annotated[
        MaintenanceDeadLetterRetirementClassification | None,
        described_field("Retirement classification."),
    ] = None
    retired_by: Annotated[str | None, described_field("Retiring actor.")] = None
    retired_at: Annotated[datetime | None, described_field("Retirement time.")] = None

    @classmethod
    def from_entity(
        cls, inspection: MaintenanceDeadLetterInspection
    ) -> MaintenanceDeadLetterInspectionResponse:
        """Map exact internal DLQ evidence to the public schema."""
        return cls(
            entry=MaintenanceDeadLetterResponse.from_entity(inspection.entry),
            original_job=(
                None
                if inspection.original_job is None
                else MaintenanceJobResponse.from_entity(inspection.original_job)
            ),
            source_request=(
                None
                if inspection.source_request is None
                else MaintenanceDeadLetterSourceRequestResponse.from_entity(
                    inspection.source_request
                )
            ),
            source_payload=inspection.source_payload,
            attempts=tuple(
                MaintenanceJobAttemptResponse.from_entity(item)
                for item in inspection.entry.attempt_history
            ),
            error_history=inspection.error_history,
            idempotency_keys=inspection.idempotency_keys,
            effect_identities=inspection.effect_identities,
            source_identity=inspection.source_identity,
            retryable=inspection.retryable,
            outcome_class=inspection.outcome_class,
            recommended_action=inspection.recommended_action,
            retired=inspection.retired,
            archive_id=inspection.archive_id,
            retirement_reason=inspection.retirement_reason,
            retirement_classification=inspection.retirement_classification,
            retired_by=inspection.retired_by,
            retired_at=inspection.retired_at,
        )


class MaintenanceDeadLetterRetryRequest(StrictSchemaModel):
    """Bounded same-ID retry request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dry_run: Annotated[bool, described_field("Preview without queue mutation.")] = False
    reason: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=500
        ),
        described_field("Operator reason for retry."),
    ] = "operator retry"


class MaintenanceDeadLetterRetryResponse(StrictSchemaModel):
    """Bounded retry result preserving same job identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: Annotated[str, described_field("Dead-letter entry ID.")]
    job_id: Annotated[str, described_field("Original job ID.")]
    dry_run: Annotated[bool, described_field("Whether the operation was a preview.")]
    retryable: Annotated[bool, described_field("Whether same-ID retry is allowed.")]
    status: Annotated[
        MaintenanceJobStatus | None, described_field("Current job status.")
    ] = None
    snapshot: Annotated[
        MaintenanceJobResponse | None, described_field("Current job snapshot.")
    ] = None
    reason: Annotated[str, described_field("Operator retry reason.")]
    outcome_class: Annotated[
        MaintenanceDeadLetterOutcomeClass, described_field("Outcome class.")
    ]

    @classmethod
    def from_entity(
        cls, result: MaintenanceDeadLetterRetryResult
    ) -> MaintenanceDeadLetterRetryResponse:
        """Map a bounded retry result."""
        return cls(
            entry_id=result.entry_id,
            job_id=result.job_id,
            dry_run=result.dry_run,
            retryable=result.retryable,
            status=result.status,
            snapshot=(
                None
                if result.snapshot is None
                else MaintenanceJobResponse.from_entity(result.snapshot)
            ),
            reason=result.reason,
            outcome_class=result.outcome_class,
        )


class MaintenanceDeadLetterReconcileItemResponse(StrictSchemaModel):
    """One note receipt verdict from batch reconciliation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: Annotated[int, described_field("Original batch item index.")]
    idempotency_key: Annotated[str, described_field("Stable mutation key.")]
    effect_identity: Annotated[str, described_field("Stable mutation identity.")]
    status: Annotated[str, described_field("Receipt status.")]
    evidence: Annotated[tuple[str, ...], described_field("Receipt evidence.")] = ()
    canonical_path: Annotated[str | None, described_field("Canonical note path.")] = (
        None
    )
    content_hash: Annotated[str | None, described_field("Observed content hash.")] = (
        None
    )

    @classmethod
    def from_entity(
        cls, item: MaintenanceDeadLetterReconcileItem
    ) -> MaintenanceDeadLetterReconcileItemResponse:
        """Map one reconciliation item."""
        return cls(
            index=item.index,
            idempotency_key=item.idempotency_key,
            effect_identity=item.effect_identity,
            status=item.status,
            evidence=item.evidence,
            canonical_path=item.canonical_path,
            content_hash=item.content_hash,
        )


class MaintenanceDeadLetterReconcileResponse(StrictSchemaModel):
    """Per-item receipt reconciliation result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: Annotated[str, described_field("Dead-letter entry ID.")]
    job_id: Annotated[str, described_field("Original job ID.")]
    outcome_class: Annotated[
        MaintenanceDeadLetterOutcomeClass, described_field("Outcome class.")
    ]
    retryable: Annotated[bool, described_field("Whether same-ID retry is allowed.")]
    items: Annotated[
        tuple[MaintenanceDeadLetterReconcileItemResponse, ...],
        described_field("Per-item receipt evidence."),
    ] = ()
    recommended_action: Annotated[str, described_field("Evidence-based next action.")]
    source_available: Annotated[
        bool, described_field("Whether the source was readable.")
    ]

    @classmethod
    def from_entity(
        cls, result: MaintenanceDeadLetterReconcileResult
    ) -> MaintenanceDeadLetterReconcileResponse:
        """Map reconciliation evidence."""
        return cls(
            entry_id=result.entry_id,
            job_id=result.job_id,
            outcome_class=result.outcome_class,
            retryable=result.retryable,
            items=tuple(
                MaintenanceDeadLetterReconcileItemResponse.from_entity(item)
                for item in result.items
            ),
            recommended_action=result.recommended_action,
            source_available=result.source_available,
        )


class MaintenanceDeadLetterRetireRequest(StrictSchemaModel):
    """Bounded provenance retirement request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=500
        ),
        described_field("Mandatory operator retirement reason."),
    ]
    classification: Annotated[
        MaintenanceDeadLetterRetirementClassification,
        described_field("Bounded retirement classification."),
    ]
    retired_by: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=120
        ),
        described_field("Actor recording the retirement."),
    ]

    @field_validator("classification", mode="before")
    @classmethod
    def parse_classification(
        cls, value: str | MaintenanceDeadLetterRetirementClassification
    ) -> MaintenanceDeadLetterRetirementClassification:
        """Parse the public JSON classification string once at the boundary."""
        return (
            value
            if isinstance(value, MaintenanceDeadLetterRetirementClassification)
            else MaintenanceDeadLetterRetirementClassification(value)
        )


class MaintenanceDeadLetterRetireResponse(StrictSchemaModel):
    """Durable retirement archive and cleanup state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: Annotated[str, described_field("Dead-letter entry ID.")]
    job_id: Annotated[str, described_field("Original job ID.")]
    archive_id: Annotated[str, described_field("Immutable archive identity.")]
    retired_by: Annotated[str, described_field("Retiring actor.")]
    retired_at: Annotated[datetime, described_field("Retirement time.")]
    reason: Annotated[str, described_field("Retirement reason.")]
    classification: Annotated[
        MaintenanceDeadLetterRetirementClassification,
        described_field("Retirement classification."),
    ]
    retired: Annotated[bool, described_field("Whether exact cleanup completed.")]
    pending_cleanup: Annotated[
        bool,
        described_field("Whether archive is durable and Redis cleanup is pending."),
    ] = False

    @classmethod
    def from_entity(
        cls, result: MaintenanceDeadLetterRetireResult
    ) -> MaintenanceDeadLetterRetireResponse:
        """Map retirement provenance."""
        return cls(
            entry_id=result.entry_id,
            job_id=result.job_id,
            archive_id=result.archive_id,
            retired_by=result.retired_by,
            retired_at=result.retired_at,
            reason=result.reason,
            classification=result.classification,
            retired=result.retired,
            pending_cleanup=result.pending_cleanup,
        )
