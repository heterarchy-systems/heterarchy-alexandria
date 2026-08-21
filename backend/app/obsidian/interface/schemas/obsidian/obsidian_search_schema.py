"""Obsidian search schema contracts."""

from __future__ import annotations

from typing import Annotated

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSearchQuery,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianRelatedNote,
    ObsidianSearchHit,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.obsidian.interface.schemas.obsidian.obsidian_note_write_schema import (
    _optional_note_type,
)
from app.obsidian.interface.schemas.obsidian.obsidian_schema import ObsidianNoteResponse
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.type_validation.frontmatter_metadata_normalization import (
    normalize_string_collection,
)
from app.shared.types.extra_types import JSONValue
from pydantic import StringConstraints, field_validator


class ObsidianSearchRequest(StrictSchemaModel):
    """Search request for Obsidian-backed Alexandria notes."""

    query: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Query for this Obsidian search request."),
    ]
    limit: Annotated[
        int, described_field("Limit for this Obsidian search request.", ge=1, le=50)
    ] = 10
    alexandria_type: Annotated[
        AlexandriaNoteType | None,
        described_field("Alexandria type for this Obsidian search request."),
    ] = None
    project: Annotated[
        str | None, described_field("Project for this Obsidian search request.")
    ] = None
    tags: Annotated[
        list[str], described_field("Tags for this Obsidian search request.")
    ] = schema_list_default()
    refresh: Annotated[
        bool, described_field("Refresh for this Obsidian search request.")
    ] = False

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: JSONValue) -> list[str]:
        """Normalize tag filters without accepting nested or numeric values.

        Args:
            value: Raw tag filter input.

        Returns:
            Canonical ordered tag filters.
        """
        return normalize_string_collection(value)

    def to_query(self) -> ObsidianSearchQuery:
        """Convert to application search query.

        Returns:
            Application search query.
        """
        return ObsidianSearchQuery(
            query=self.query,
            limit=self.limit,
            alexandria_type=_optional_note_type(self.alexandria_type),
            project=self.project,
            tags=tuple(self.tags),
        )


class ObsidianSearchHitResponse(StrictSchemaModel):
    """One Obsidian search hit."""

    note: Annotated[
        ObsidianNoteResponse,
        described_field("Note for this Obsidian search hit response."),
    ]
    excerpt: Annotated[
        str, described_field("Excerpt for this Obsidian search hit response.")
    ]
    score: Annotated[
        float, described_field("Score for this Obsidian search hit response.")
    ]
    chunk_id: Annotated[
        str | None,
        described_field("Chunk identifier for this Obsidian search hit response."),
    ]
    heading_path: Annotated[
        str | None,
        described_field("Heading path for this Obsidian search hit response."),
    ]

    @classmethod
    def from_entity(cls, hit: ObsidianSearchHit) -> ObsidianSearchHitResponse:
        """Create schema from search hit.

        Args:
            hit: Domain search hit.

        Returns:
            HTTP search hit schema.
        """
        return cls(
            note=ObsidianNoteResponse.from_entity(hit.note),
            excerpt=hit.excerpt,
            score=hit.score,
            chunk_id=hit.chunk_id,
            heading_path=hit.heading_path,
        )


class ObsidianSearchResponse(StrictSchemaModel):
    """Obsidian search response."""

    items: Annotated[
        list[ObsidianSearchHitResponse],
        described_field("Items for this Obsidian search response."),
    ]
    total: Annotated[int, described_field("Total for this Obsidian search response.")]


class ObsidianRelatedNoteResponse(StrictSchemaModel):
    """One graph-related Obsidian note."""

    note: Annotated[
        ObsidianNoteResponse,
        described_field("Note for this Obsidian related note response."),
    ]
    relation: Annotated[
        ObsidianRelationType,
        described_field("Relation for this Obsidian related note response."),
    ]
    source_kind: Annotated[
        ObsidianEdgeSourceKind,
        described_field("Source kind for this Obsidian related note response."),
    ]
    direction: Annotated[
        str, described_field("Direction for this Obsidian related note response.")
    ]
    score: Annotated[
        float, described_field("Score for this Obsidian related note response.")
    ]
    edge_id: Annotated[
        str, described_field("Edge identifier for this Obsidian related note response.")
    ]

    @classmethod
    def from_entity(cls, item: ObsidianRelatedNote) -> ObsidianRelatedNoteResponse:
        """Create schema from related-note entity.

        Args:
            item: Related-note entity.

        Returns:
            HTTP related-note schema.
        """
        return cls(
            note=ObsidianNoteResponse.from_entity(item.note),
            relation=item.relation,
            source_kind=item.source_kind,
            direction=item.direction,
            score=item.score,
            edge_id=item.edge_id,
        )


class ObsidianRelatedNotesResponse(StrictSchemaModel):
    """Related notes response."""

    items: Annotated[
        list[ObsidianRelatedNoteResponse],
        described_field("Items for this Obsidian related notes response."),
    ]
    total: Annotated[
        int, described_field("Total for this Obsidian related notes response.")
    ]
