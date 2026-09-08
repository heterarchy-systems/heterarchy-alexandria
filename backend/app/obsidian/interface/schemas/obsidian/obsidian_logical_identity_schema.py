"""Shared strict HTTP schema for canonical logical note identity."""

from __future__ import annotations

from datetime import date as calendar_date
from typing import Annotated

from pydantic import StringConstraints, field_validator

from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field

_IDENTITY_TEXT = StringConstraints(strict=True, min_length=1, max_length=256)


class ObsidianLogicalIdentitySchema(StrictSchemaModel):
    """Bounded project/report/date/entity identity at an external boundary."""

    project: Annotated[
        str,
        _IDENTITY_TEXT,
        described_field("Project for this Obsidian logical identity."),
    ]
    report: Annotated[
        str,
        _IDENTITY_TEXT,
        described_field("Report family for this Obsidian logical identity."),
    ]
    date: Annotated[
        str,
        StringConstraints(strict=True, min_length=10, max_length=10),
        described_field("ISO calendar date for this Obsidian logical identity."),
    ]
    entity: Annotated[
        str,
        _IDENTITY_TEXT,
        described_field("Entity for this Obsidian logical identity."),
    ]
    edition: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=256),
        described_field("Optional edition for this Obsidian logical identity."),
    ] = None

    @field_validator("project", "report", "entity", mode="after")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        """Reject whitespace-only identity components."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("logical identity text must not be blank")
        return normalized

    @field_validator("edition", mode="after")
    @classmethod
    def normalize_edition(cls, value: str | None) -> str | None:
        """Normalize an optional edition while preserving omission semantics."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("logical identity edition must not be blank")
        return normalized

    @field_validator("date", mode="after")
    @classmethod
    def validate_iso_date(cls, value: str) -> str:
        """Validate a real ISO calendar date rather than only its shape."""
        try:
            parsed = calendar_date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("logical identity date must be a valid ISO date") from exc
        return parsed.isoformat()

    def to_identity(self) -> ObsidianLogicalIdentity:
        """Convert the boundary schema to the shared domain value object."""
        return ObsidianLogicalIdentity(
            project=self.project,
            report=self.report,
            date=self.date,
            entity=self.entity,
            edition=self.edition,
        )

    @classmethod
    def from_identity(
        cls,
        identity: ObsidianLogicalIdentity,
    ) -> ObsidianLogicalIdentitySchema:
        """Create the boundary representation from the shared domain value."""
        return cls(
            project=identity.project,
            report=identity.report,
            date=identity.date,
            entity=identity.entity,
            edition=identity.edition,
        )
