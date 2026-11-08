"""Obsidian search schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSearchQuery
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianRelatedNote,
    ObsidianSearchHit,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.obsidian.interface.schemas.obsidian.notes.obsidian_note_schema import (
    ObsidianNoteResponse,
    _optional_note_type,
)
from app.obsidian.interface.schemas.obsidian.obsidian_string_types import (
    ObsidianQueryText,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default
from app.shared.type_validation.frontmatter_metadata_normalization import (
    normalize_string_collection,
)
from app.shared.types.extra_types import JSONValue


class ObsidianSearchRequest(StrictSchemaModel):
    """Search request for Obsidian-backed Alexandria notes."""

    query: Annotated[
        ObsidianQueryText, Field(description="Query for this Obsidian search request.")
    ]
    limit: Annotated[
        int, Field(description="Limit for this Obsidian search request.", ge=1, le=50)
    ] = 10
    alexandria_type: Annotated[
        AlexandriaNoteType | None,
        Field(description="Alexandria type for this Obsidian search request."),
    ] = None
    project: Annotated[
        str | None, Field(description="Project for this Obsidian search request.")
    ] = None
    tags: Annotated[
        list[str], Field(description="Tags for this Obsidian search request.")
    ] = schema_list_default()
    refresh: Annotated[
        bool, Field(description="Refresh for this Obsidian search request.")
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
        Field(description="Note for this Obsidian search hit response."),
    ]
    excerpt: Annotated[
        str, Field(description="Excerpt for this Obsidian search hit response.")
    ]
    score: Annotated[
        float, Field(description="Score for this Obsidian search hit response.")
    ]
    chunk_id: Annotated[
        str | None,
        Field(description="Chunk identifier for this Obsidian search hit response."),
    ]
    heading_path: Annotated[
        str | None,
        Field(description="Heading path for this Obsidian search hit response."),
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
        Field(description="Items for this Obsidian search response."),
    ]
    total: Annotated[int, Field(description="Total for this Obsidian search response.")]


class ObsidianRelatedNoteResponse(StrictSchemaModel):
    """One graph-related Obsidian note."""

    note: Annotated[
        ObsidianNoteResponse,
        Field(description="Note for this Obsidian related note response."),
    ]
    relation: Annotated[
        ObsidianRelationType,
        Field(description="Relation for this Obsidian related note response."),
    ]
    source_kind: Annotated[
        ObsidianEdgeSourceKind,
        Field(description="Source kind for this Obsidian related note response."),
    ]
    direction: Annotated[
        str, Field(description="Direction for this Obsidian related note response.")
    ]
    score: Annotated[
        float, Field(description="Score for this Obsidian related note response.")
    ]
    edge_id: Annotated[
        str,
        Field(description="Edge identifier for this Obsidian related note response."),
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
        Field(description="Items for this Obsidian related notes response."),
    ]
    total: Annotated[
        int, Field(description="Total for this Obsidian related notes response.")
    ]
