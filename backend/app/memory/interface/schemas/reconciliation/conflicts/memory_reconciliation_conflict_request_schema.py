"""Strict conflict resolution request schema for memory reconciliation."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryConflictStatus,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.types.types_convert_utils import enum_value
from pydantic import StringConstraints, field_validator


class MemoryConflictResolutionRequest(StrictSchemaModel):
    """Explicit final resolution for one first-class memory conflict."""

    status: Annotated[
        MemoryConflictStatus,
        described_field("Status for this memory conflict resolution request."),
    ]
    resolution: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=10000),
        described_field("Resolution for this memory conflict resolution request."),
    ]

    @field_validator("status")
    @classmethod
    def require_resolved_status(
        cls,
        value: MemoryConflictStatus | str,
    ) -> MemoryConflictStatus:
        """Reject non-final conflict states at the HTTP boundary.

        Args:
            value: Value.

        Returns:
            MemoryConflictStatus: Operation result.
        """
        normalized = enum_value(value, MemoryConflictStatus, "status")
        if not normalized.value.startswith("RESOLVED_"):
            raise ValueError("memory conflict resolution requires a RESOLVED_* status")
        return normalized

    @field_validator("resolution")
    @classmethod
    def normalize_resolution(cls, value: str) -> str:
        """Normalize and require a concrete resolution explanation.

        Args:
            value: Value.

        Returns:
            str: Operation result.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("memory conflict resolution is required")
        return normalized
