"""Obsidian note read and write schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianNoteWriteResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianFrontmatterMode,
    ObsidianIndexStatus,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
    ObsidianWriteOperation,
)
from app.obsidian.interface.schemas.obsidian.obsidian_mutation_outcome_schema import (
    ObsidianMutationOutcomeResponseSchema,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    schema_dict_default,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.type_validation.frontmatter_metadata_normalization import (
    normalize_known_frontmatter_metadata,
    normalize_string_collection,
)
from app.shared.types.extra_types import JSONObject, JSONValue


class ObsidianNoteResponse(StrictSchemaModel):
    """One indexed Obsidian note response."""

    id: Annotated[
        str, Field(description="Stable identifier for this Obsidian note response.")
    ]
    mutation_receipt: Annotated[
        ObsidianMutationOutcomeResponseSchema | None,
        Field(
            description="Write receipt for mutations; null for ordinary source reads."
        ),
    ] = None
    alexandria_type: Annotated[
        AlexandriaNoteType,
        Field(description="Alexandria type for this Obsidian note response."),
    ]
    path: Annotated[str, Field(description="Path for this Obsidian note response.")]
    title: Annotated[str, Field(description="Title for this Obsidian note response.")]
    status: Annotated[str, Field(description="Status for this Obsidian note response.")]
    tags: Annotated[
        list[str], Field(description="Tags for this Obsidian note response.")
    ]
    project: Annotated[
        str | None, Field(description="Project for this Obsidian note response.")
    ]
    source: Annotated[
        str | None, Field(description="Source for this Obsidian note response.")
    ]
    content_hash: Annotated[
        str, Field(description="Content hash for this Obsidian note response.")
    ]
    frontmatter: Annotated[
        JSONObject, Field(description="Frontmatter for this Obsidian note response.")
    ]
    body: Annotated[str, Field(description="Body for this Obsidian note response.")]
    index_status: Annotated[
        ObsidianIndexStatus,
        Field(description="Index status for this Obsidian note response."),
    ]
    error_message: Annotated[
        str | None, Field(description="Error message for this Obsidian note response.")
    ]
    size_bytes: Annotated[
        int, Field(description="Size bytes for this Obsidian note response.")
    ]
    modified_at: Annotated[
        AwareTimestamp,
        Field(description="Modified at for this Obsidian note response."),
    ]
    indexed_at: Annotated[
        AwareTimestamp | None,
        Field(description="Indexed at for this Obsidian note response."),
    ]
    wikilink: Annotated[
        str, Field(description="Wikilink for this Obsidian note response.")
    ]

    @classmethod
    def from_entity(cls, note: ObsidianNote) -> ObsidianNoteResponse:
        """Create schema from entity.

        Args:
            note: Domain note entity.

        Returns:
            HTTP response schema.
        """
        return cls(
            id=note.note_id,
            mutation_receipt=None
            if note.mutation_receipt is None
            else ObsidianMutationOutcomeResponseSchema.from_entity(
                note.mutation_receipt
            ),
            alexandria_type=note.alexandria_type,
            path=note.relative_path,
            title=note.title,
            status=note.status,
            tags=list(note.tags),
            project=note.project,
            source=note.source,
            content_hash=note.content_hash,
            frontmatter=note.frontmatter,
            body=note.body,
            index_status=note.index_status,
            error_message=note.error_message,
            size_bytes=note.size_bytes,
            modified_at=note.modified_at,
            indexed_at=note.indexed_at,
            wikilink=f"[[{note.relative_path.removesuffix('.md')}]]",
        )


class ObsidianSaveNoteRequest(StrictSchemaModel):
    """Request to create one Alexandria-managed Obsidian note."""

    title: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Title for this Obsidian save note request."),
    ]
    body: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Body for this Obsidian save note request."),
    ]
    alexandria_type: Annotated[
        AlexandriaNoteType,
        Field(description="Alexandria type for this Obsidian save note request."),
    ]
    id: Annotated[
        str | None,
        Field(description="Stable identifier for this Obsidian save note request."),
    ] = None
    path: Annotated[
        str | None, Field(description="Path for this Obsidian save note request.")
    ] = None
    tags: Annotated[
        list[str], Field(description="Tags for this Obsidian save note request.")
    ] = schema_list_default()
    status: Annotated[
        str, Field(description="Status for this Obsidian save note request.")
    ] = "active"
    project: Annotated[
        str | None, Field(description="Project for this Obsidian save note request.")
    ] = None
    source: Annotated[
        str, Field(description="Source for this Obsidian save note request.")
    ] = "mcp"
    frontmatter: Annotated[
        JSONObject,
        Field(description="Frontmatter for this Obsidian save note request."),
    ] = schema_dict_default()
    expected_content_hash: Annotated[
        str | None,
        StringConstraints(
            strict=True, min_length=64, max_length=64, pattern="^[0-9a-f]{64}$"
        ),
        Field(description="Expected content hash for this Obsidian save note request."),
    ] = None
    idempotency_key: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=512),
        Field(
            description="Retry-stable mutation identity; omitted keys derive from the exact request."
        ),
    ] = None

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: JSONValue) -> list[str]:
        """Normalize note tags at the external HTTP boundary.

        Args:
            value: Raw note tag input.

        Returns:
            Canonical ordered note tags.
        """
        return normalize_string_collection(value)

    @field_validator("frontmatter", mode="before")
    @classmethod
    def normalize_frontmatter(cls, value: JSONObject) -> JSONObject:
        """Normalize known typed metadata before building the internal command.

        Args:
            value: Raw JSON-compatible frontmatter payload.

        Returns:
            Copied frontmatter with canonical collection and Boolean values.
        """
        normalized = dict(value)
        normalize_known_frontmatter_metadata(normalized)
        return normalized

    def to_command(self) -> ObsidianSaveNote:
        """Convert request into application save command.

        Returns:
            Application save command.
        """
        return ObsidianSaveNote(
            title=self.title,
            body=self.body,
            alexandria_type=_note_type(self.alexandria_type),
            note_id=self.id,
            relative_path=self.path,
            tags=tuple(self.tags),
            status=self.status,
            project=self.project,
            source=self.source,
            frontmatter=self.frontmatter,
            expected_content_hash=self.expected_content_hash,
            idempotency_key=self.idempotency_key,
        )


class ObsidianWriteNoteRequest(ObsidianSaveNoteRequest):
    """Explicit note write request with exact identity and merge semantics."""

    match_by: ObsidianWriteMatchBy
    frontmatter_mode: ObsidianFrontmatterMode = ObsidianFrontmatterMode.MERGE

    def to_write_command(self, write_mode: ObsidianWriteMode) -> ObsidianWriteNote:
        """Convert the external request to an explicit application command.

        Args:
            write_mode: Value supplied to to_write_command.

        Returns:
            Result produced by to_write_command.
        """
        return ObsidianWriteNote(
            note=self.to_command(),
            write_mode=write_mode,
            match_by=ObsidianWriteMatchBy(self.match_by),
            frontmatter_mode=ObsidianFrontmatterMode(self.frontmatter_mode),
            provided_fields=frozenset(self.model_fields_set),
        )


class ObsidianWritePipelineResponse(StrictSchemaModel):
    """Observed stages completed by one explicit canonical note write."""

    storage_status: Annotated[
        str,
        Field(description="Storage status for this Obsidian write pipeline response."),
    ]
    metadata_status: Annotated[
        str,
        Field(description="Metadata status for this Obsidian write pipeline response."),
    ]
    fts_status: Annotated[
        str, Field(description="FTS status for this Obsidian write pipeline response.")
    ]
    graph_edge_index_status: Annotated[
        str,
        Field(
            description="Graph edge index status for this Obsidian write pipeline response."
        ),
    ]
    graph_projection_status: Annotated[
        str,
        Field(
            description="Graph projection status for this Obsidian write pipeline response."
        ),
    ]


class ObsidianNoteWriteResponse(StrictSchemaModel):
    """Explicit write outcome without overloading note index status."""

    operation: Annotated[
        ObsidianWriteOperation,
        Field(description="Operation for this Obsidian note write response."),
    ]
    write_mode: Annotated[
        ObsidianWriteMode,
        Field(description="Write mode for this Obsidian note write response."),
    ]
    match_by: Annotated[
        ObsidianWriteMatchBy,
        Field(description="Match by for this Obsidian note write response."),
    ]
    note: Annotated[
        ObsidianNoteResponse,
        Field(description="Note for this Obsidian note write response."),
    ]
    pipeline: Annotated[
        ObsidianWritePipelineResponse,
        Field(description="Pipeline for this Obsidian note write response."),
    ]
    reindex_required: Annotated[
        bool,
        Field(description="Reindex required for this Obsidian note write response."),
    ]
    warnings: Annotated[
        list[str], Field(description="Warnings for this Obsidian note write response.")
    ]

    @classmethod
    def from_entity(
        cls,
        result: ObsidianNoteWriteResult,
    ) -> ObsidianNoteWriteResponse:
        """Create a response from the domain write outcome.

        Args:
            result: Value supplied to from_entity.

        Returns:
            Result produced by from_entity.
        """
        return cls(
            operation=result.operation,
            write_mode=result.write_mode,
            match_by=result.match_by,
            note=ObsidianNoteResponse.from_entity(result.note),
            pipeline=ObsidianWritePipelineResponse(
                storage_status=result.storage_status,
                metadata_status=result.metadata_status,
                fts_status=result.fts_status,
                graph_edge_index_status=result.graph_edge_index_status,
                graph_projection_status=result.graph_projection_status,
            ),
            reindex_required=result.reindex_required,
            warnings=list(result.warnings),
        )


def _note_type(value: AlexandriaNoteType | str) -> AlexandriaNoteType:
    """Execute note type.

    Args:
        value: Value being processed.

    Returns:
        AlexandriaNoteType result produced by note type.
    """
    if isinstance(value, AlexandriaNoteType):
        return value
    return AlexandriaNoteType(value)


def _optional_note_type(
    value: AlexandriaNoteType | str | None,
) -> AlexandriaNoteType | None:
    """Execute optional note type.

    Args:
        value: Value being processed.

    Returns:
        AlexandriaNoteType | None result produced by optional note type.
    """
    if value is None:
        return None
    return _note_type(value)
