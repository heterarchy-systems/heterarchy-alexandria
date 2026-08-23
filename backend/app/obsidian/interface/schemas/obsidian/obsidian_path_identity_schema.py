"""Obsidian path identity schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.obsidian.domain.entities.obsidian_note import (
    ObsidianCanonicalIdentityResult,
    ObsidianExactPathStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianIndexStatus,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
)


class ObsidianExactPathStatusResponse(StrictSchemaModel):
    """Exact managed-path existence response."""

    exists: Annotated[
        bool, described_field("Exists for this Obsidian exact path status response.")
    ]
    note_id: Annotated[
        str | None,
        described_field(
            "Note identifier for this Obsidian exact path status response."
        ),
    ]
    path: Annotated[
        str, described_field("Path for this Obsidian exact path status response.")
    ]
    index_status: Annotated[
        ObsidianIndexStatus | None,
        described_field("Index status for this Obsidian exact path status response."),
    ]

    @classmethod
    def from_entity(
        cls,
        result: ObsidianExactPathStatus,
    ) -> ObsidianExactPathStatusResponse:
        """Create an exact-path response.

        Args:
            result: Value supplied to from_entity.

        Returns:
            Result produced by from_entity.
        """
        return cls(
            exists=result.exists,
            note_id=result.note_id,
            path=result.relative_path,
            index_status=result.index_status,
        )


class ObsidianCanonicalIdentityRequest(StrictSchemaModel):
    """Logical report identity used for alias-aware resolution."""

    project: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Project for this Obsidian canonical identity request."),
    ]
    report: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Report for this Obsidian canonical identity request."),
    ]
    date: Annotated[
        str,
        StringConstraints(strict=True, pattern="^\\d{4}-\\d{2}-\\d{2}$"),
        described_field("Date for this Obsidian canonical identity request."),
    ]
    entity: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Entity for this Obsidian canonical identity request."),
    ]
    edition: Annotated[
        str | None,
        described_field("Edition for this Obsidian canonical identity request."),
    ] = None


class ObsidianCanonicalIdentityResponse(StrictSchemaModel):
    """Canonical report family/path resolution response."""

    canonical_report_family: Annotated[
        str,
        described_field(
            "Canonical report family for this Obsidian canonical identity response."
        ),
    ]
    canonical_entity: Annotated[
        str,
        described_field(
            "Canonical entity for this Obsidian canonical identity response."
        ),
    ]
    canonical_path: Annotated[
        str,
        described_field(
            "Canonical path for this Obsidian canonical identity response."
        ),
    ]
    existing_note_id: Annotated[
        str | None,
        described_field(
            "Existing note identifier for this Obsidian canonical identity response."
        ),
    ]
    aliases: Annotated[
        list[str],
        described_field("Aliases for this Obsidian canonical identity response."),
    ]
    resolution: Annotated[
        str,
        described_field("Resolution for this Obsidian canonical identity response."),
    ]
    candidate_paths: Annotated[
        list[str],
        described_field(
            "Candidate paths for this Obsidian canonical identity response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        result: ObsidianCanonicalIdentityResult,
    ) -> ObsidianCanonicalIdentityResponse:
        """Create a canonical identity response.

        Args:
            result: Value supplied to from_entity.

        Returns:
            Result produced by from_entity.
        """
        return cls(
            canonical_report_family=result.canonical_report_family,
            canonical_entity=result.canonical_entity,
            canonical_path=result.canonical_path,
            existing_note_id=result.existing_note_id,
            aliases=list(result.aliases),
            resolution=result.resolution,
            candidate_paths=list(result.candidate_paths),
        )
