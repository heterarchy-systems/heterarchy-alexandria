"""HTTP schemas for maintenance dead-letter inspection."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field

from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterEntry,
    MaintenanceDeadLetterInspection,
    MaintenanceJobAttempt,
    MaintenanceJobRequest,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterOutcomeClass,
    MaintenanceDeadLetterRetirementClassification,
    MaintenanceJobKind,
)
from app.operations.interface.schemas.operations.maintenance.job_schema import (
    MaintenanceJobResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.types.extra_types import JSONValue


class MaintenanceDeadLetterResponse(StrictSchemaModel):
    """One terminal job failure recorded in the dead-letter stream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: Annotated[
        str,
        Field(description="Entry identifier for this dead-letter response."),
    ]
    job_id: Annotated[
        str,
        Field(description="Job identifier for this dead-letter response."),
    ]
    kind: Annotated[
        MaintenanceJobKind,
        Field(description="Kind for this dead-letter response."),
    ]
    attempts: Annotated[
        int,
        Field(description="Attempts for this dead-letter response."),
    ]
    failed_at: Annotated[
        datetime,
        Field(description="Failed at for this dead-letter response."),
    ]
    error_summary: Annotated[
        str,
        Field(description="Error summary for this dead-letter response."),
    ]
    source_stream_id: Annotated[
        str,
        Field(description="Source stream identifier for this dead-letter response."),
    ]
    lifecycle: Annotated[
        str,
        Field(description="Redis lifecycle reservation for this dead-letter response."),
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
        Field(description="Entries for this dead-letter list response."),
    ] = ()


class MaintenanceDeadLetterPurgeResponse(StrictSchemaModel):
    """Result of dropping every dead-letter entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    purged: Annotated[
        int,
        Field(description="Purged entry count for this dead-letter purge response."),
    ]


class MaintenanceDeadLetterSourceRequestResponse(StrictSchemaModel):
    """Original typed request retained in the Redis source stream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Annotated[MaintenanceJobKind, Field(description="Original job kind.")]
    requested_by: Annotated[str, Field(description="Original requester.")]
    source_id: Annotated[str, Field(description="Original stable source identity.")]
    limit: Annotated[int, Field(description="Original bounded operation limit.")]
    force: Annotated[bool, Field(description="Original force flag.")]

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

    attempt: Annotated[int, Field(description="Attempt number.")]
    status: Annotated[str, Field(description="Attempt lifecycle status.")]
    occurred_at: Annotated[datetime, Field(description="Attempt event time.")]
    error_summary: Annotated[str | None, Field(description="Attempt error.")] = None

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
        Field(description="Exact dead-letter entry."),
    ]
    original_job: Annotated[
        MaintenanceJobResponse | None,
        Field(description="Current original job snapshot."),
    ] = None
    source_request: Annotated[
        MaintenanceDeadLetterSourceRequestResponse | None,
        Field(description="Original source request when retained."),
    ] = None
    source_payload: Annotated[
        dict[str, JSONValue] | None,
        Field(description="Durable batch payload when available."),
    ] = None
    attempts: Annotated[
        tuple[MaintenanceJobAttemptResponse, ...],
        Field(description="Retained attempt history."),
    ] = ()
    error_history: Annotated[
        tuple[str, ...], Field(description="Retained error history.")
    ] = ()
    idempotency_keys: Annotated[
        tuple[str, ...], Field(description="Stable effect idempotency keys.")
    ] = ()
    effect_identities: Annotated[
        tuple[str, ...], Field(description="Stable effect identities.")
    ] = ()
    source_identity: Annotated[str, Field(description="Stable source identity.")]
    retryable: Annotated[bool, Field(description="Whether same-ID retry is allowed.")]
    outcome_class: Annotated[
        MaintenanceDeadLetterOutcomeClass,
        Field(description="Evidence outcome class."),
    ]
    recommended_action: Annotated[str, Field(description="Evidence-based next action.")]
    retired: Annotated[
        bool, Field(description="Whether this is archived evidence.")
    ] = False
    archive_id: Annotated[str | None, Field(description="Retirement archive ID.")] = (
        None
    )
    retirement_reason: Annotated[
        str | None, Field(description="Retirement reason.")
    ] = None
    retirement_classification: Annotated[
        MaintenanceDeadLetterRetirementClassification | None,
        Field(description="Retirement classification."),
    ] = None
    retired_by: Annotated[str | None, Field(description="Retiring actor.")] = None
    retired_at: Annotated[datetime | None, Field(description="Retirement time.")] = None

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
