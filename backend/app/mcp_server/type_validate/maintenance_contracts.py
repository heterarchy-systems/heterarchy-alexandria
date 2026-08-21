"""Pydantic contracts for maintenance MCP tool inputs."""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, StringConstraints, field_validator

from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.types.extra_types import JSONObject


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
        described_field(
            "Requested by for this maintenance embedding reindex tool request."
        ),
    ] = "mcp"
    source_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=200),
        described_field(
            "Source identifier for this maintenance embedding reindex tool request."
        ),
    ] = "manual"
    limit: Annotated[
        int,
        described_field(
            "Limit for this maintenance embedding reindex tool request.", ge=1, le=1000
        ),
    ] = 250
    force: Annotated[
        bool,
        described_field("Force for this maintenance embedding reindex tool request."),
    ] = False

    @field_validator("requested_by", "source_id")
    @classmethod
    def normalize_nonblank_text(cls, value: str) -> str:
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


class MaintenanceJobIdToolRequest(StrictSchemaModel):
    """Validated MCP input for one maintenance job lookup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
        described_field("Job identifier for this maintenance job ID tool request."),
    ]

    @field_validator("job_id")
    @classmethod
    def normalize_job_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("job_id must not be blank")
        return normalized
