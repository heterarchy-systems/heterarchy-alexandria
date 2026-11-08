"""Pydantic contracts for maintenance MCP tool inputs."""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints, field_validator

from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterRetirementClassification,
)
from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.types.extra_types import JSONObject, JSONValue


class MaintenanceEmbeddingReindexToolRequest(StrictSchemaModel):
    """Validated MCP input for a queued embedding reindex job."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    requested_by: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=120),
        Field(
            description="Requested by for this maintenance embedding reindex tool request."
        ),
    ] = "mcp"
    source_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=200),
        Field(
            description="Source identifier for this maintenance embedding reindex tool request."
        ),
    ] = "manual"
    limit: Annotated[
        int,
        Field(
            description="Limit for this maintenance embedding reindex tool request.",
            ge=1,
            le=1000,
        ),
    ] = 250
    force: Annotated[
        bool,
        Field(description="Force for this maintenance embedding reindex tool request."),
    ] = False

    @field_validator("requested_by", "source_id")
    @classmethod
    def normalize_nonblank_text(cls, value: str) -> str:
        """Normalize required nonblank text.

        Args:
            value: Value to transform.

        Returns:
            Normalized value.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    def to_payload(self) -> JSONObject:
        """Return the explicit backend request payload.

        Returns:
            JSON object accepted by the backend maintenance submission endpoint.
        """
        return {
            "requested_by": self.requested_by,
            "source_id": self.source_id,
            "limit": self.limit,
            "force": self.force,
        }


class MaintenanceBatchNoteWriteToolRequest(StrictSchemaModel):
    """Validated MCP input for a queued asynchronous batch note write."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    requested_by: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=120),
        Field(
            description="Requested by for this maintenance batch note write tool request."
        ),
    ] = "mcp"
    operations: Annotated[
        list[dict[str, JSONValue]],
        Field(
            description="JSON write operations for this maintenance batch note write tool request."
        ),
        Field(min_length=1, max_length=50),
    ]

    @field_validator("requested_by")
    @classmethod
    def normalize_nonblank_requested_by(cls, value: str) -> str:
        """Normalize the requested-by identity.

        Args:
            value: Value to transform.

        Returns:
            Normalized value.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("requested_by must not be blank")
        return normalized

    def to_payload(self) -> JSONObject:
        """Return the explicit backend request payload.

        Returns:
            JSON object accepted by the backend batch write job endpoint.
        """
        return {
            "requested_by": self.requested_by,
            "operations": list(self.operations),
        }


class MaintenanceJobIdToolRequest(StrictSchemaModel):
    """Validated MCP input for one maintenance job lookup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
        Field(description="Job identifier for this maintenance job ID tool request."),
    ]

    @field_validator("job_id")
    @classmethod
    def normalize_job_id(cls, value: str) -> str:
        """Normalize a maintenance job identifier.

        Args:
            value: Value to transform.

        Returns:
            Normalized value.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("job_id must not be blank")
        return normalized


class MaintenanceDeadLetterIdToolRequest(StrictSchemaModel):
    """Validated MCP input for one dead-letter entry operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
        Field(description="Entry identifier for this dead-letter ID tool request."),
    ]

    @field_validator("entry_id")
    @classmethod
    def normalize_entry_id(cls, value: str) -> str:
        """Normalize a dead-letter stream entry identifier.

        Args:
            value: Value to transform.

        Returns:
            Normalized value.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("entry_id must not be blank")
        return normalized


class MaintenanceDeadLetterRetryToolRequest(StrictSchemaModel):
    """Validated MCP input for same-ID dead-letter retry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
        Field(description="Entry identifier for this dead-letter retry request."),
    ]
    dry_run: Annotated[
        bool, Field(description="Preview retry without queue mutation.")
    ] = False
    reason: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=500),
        Field(description="Operator reason for this dead-letter retry."),
    ]

    @field_validator("entry_id", "reason")
    @classmethod
    def normalize_retry_text(cls, value: str) -> str:
        """Normalize required retry text."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("retry text must not be blank")
        return normalized

    def to_payload(self) -> JSONObject:
        """Return the backend retry request payload."""
        return {"dry_run": self.dry_run, "reason": self.reason}


class MaintenanceDeadLetterRetireToolRequest(StrictSchemaModel):
    """Validated MCP input for provenance-preserving retirement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
        Field(description="Entry identifier for this dead-letter retirement."),
    ]
    reason: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=500),
        Field(description="Mandatory retirement reason."),
    ]
    classification: Annotated[
        MaintenanceDeadLetterRetirementClassification,
        Field(description="Bounded retirement classification."),
    ]
    retired_by: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=120),
        Field(description="Retiring actor."),
    ]

    @field_validator("classification", mode="before")
    @classmethod
    def parse_classification(
        cls, value: str | MaintenanceDeadLetterRetirementClassification
    ) -> MaintenanceDeadLetterRetirementClassification:
        """Parse the public MCP classification string."""
        return (
            value
            if isinstance(value, MaintenanceDeadLetterRetirementClassification)
            else MaintenanceDeadLetterRetirementClassification(value)
        )

    @field_validator("entry_id", "reason", "retired_by")
    @classmethod
    def normalize_retirement_text(cls, value: str) -> str:
        """Normalize required retirement text."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("retirement text must not be blank")
        return normalized

    def to_payload(self) -> JSONObject:
        """Return the backend retirement request payload."""
        return {
            "reason": self.reason,
            "classification": str(self.classification),
            "retired_by": self.retired_by,
        }
