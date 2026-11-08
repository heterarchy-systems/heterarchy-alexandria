"""HTTP schemas for maintenance dead-letter lifecycle actions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints, field_validator

from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterReconcileItem,
    MaintenanceDeadLetterReconcileResult,
    MaintenanceDeadLetterRetireResult,
    MaintenanceDeadLetterRetryResult,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterOutcomeClass,
    MaintenanceDeadLetterRetirementClassification,
    MaintenanceJobStatus,
)
from app.operations.interface.schemas.operations.maintenance.job_schema import (
    MaintenanceJobResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel


class MaintenanceDeadLetterRetryRequest(StrictSchemaModel):
    """Bounded same-ID retry request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dry_run: Annotated[bool, Field(description="Preview without queue mutation.")] = (
        False
    )
    reason: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=500
        ),
        Field(description="Operator reason for retry."),
    ] = "operator retry"


class MaintenanceDeadLetterRetryResponse(StrictSchemaModel):
    """Bounded retry result preserving same job identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: Annotated[str, Field(description="Dead-letter entry ID.")]
    job_id: Annotated[str, Field(description="Original job ID.")]
    dry_run: Annotated[bool, Field(description="Whether the operation was a preview.")]
    retryable: Annotated[bool, Field(description="Whether same-ID retry is allowed.")]
    status: Annotated[
        MaintenanceJobStatus | None, Field(description="Current job status.")
    ] = None
    snapshot: Annotated[
        MaintenanceJobResponse | None, Field(description="Current job snapshot.")
    ] = None
    reason: Annotated[str, Field(description="Operator retry reason.")]
    outcome_class: Annotated[
        MaintenanceDeadLetterOutcomeClass, Field(description="Outcome class.")
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

    index: Annotated[int, Field(description="Original batch item index.")]
    idempotency_key: Annotated[str, Field(description="Stable mutation key.")]
    effect_identity: Annotated[str, Field(description="Stable mutation identity.")]
    status: Annotated[str, Field(description="Receipt status.")]
    evidence: Annotated[tuple[str, ...], Field(description="Receipt evidence.")] = ()
    canonical_path: Annotated[str | None, Field(description="Canonical note path.")] = (
        None
    )
    content_hash: Annotated[str | None, Field(description="Observed content hash.")] = (
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

    entry_id: Annotated[str, Field(description="Dead-letter entry ID.")]
    job_id: Annotated[str, Field(description="Original job ID.")]
    outcome_class: Annotated[
        MaintenanceDeadLetterOutcomeClass, Field(description="Outcome class.")
    ]
    retryable: Annotated[bool, Field(description="Whether same-ID retry is allowed.")]
    items: Annotated[
        tuple[MaintenanceDeadLetterReconcileItemResponse, ...],
        Field(description="Per-item receipt evidence."),
    ] = ()
    recommended_action: Annotated[str, Field(description="Evidence-based next action.")]
    source_available: Annotated[
        bool, Field(description="Whether the source was readable.")
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
        Field(description="Mandatory operator retirement reason."),
    ]
    classification: Annotated[
        MaintenanceDeadLetterRetirementClassification,
        Field(description="Bounded retirement classification."),
    ]
    retired_by: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=120
        ),
        Field(description="Actor recording the retirement."),
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

    entry_id: Annotated[str, Field(description="Dead-letter entry ID.")]
    job_id: Annotated[str, Field(description="Original job ID.")]
    archive_id: Annotated[str, Field(description="Immutable archive identity.")]
    retired_by: Annotated[str, Field(description="Retiring actor.")]
    retired_at: Annotated[datetime, Field(description="Retirement time.")]
    reason: Annotated[str, Field(description="Retirement reason.")]
    classification: Annotated[
        MaintenanceDeadLetterRetirementClassification,
        Field(description="Retirement classification."),
    ]
    retired: Annotated[bool, Field(description="Whether exact cleanup completed.")]
    pending_cleanup: Annotated[
        bool,
        Field(description="Whether archive is durable and Redis cleanup is pending."),
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
