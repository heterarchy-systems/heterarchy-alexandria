"""Obsidian note write schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, field_validator

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNoteWriteResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianFrontmatterMode,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
    ObsidianWriteOperation,
)
from app.obsidian.interface.schemas.obsidian.obsidian_schema import ObsidianNoteResponse
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_dict_default,
    schema_list_default,
)
from app.shared.type_validation.frontmatter_metadata_normalization import (
    normalize_known_frontmatter_metadata,
    normalize_string_collection,
)
from app.shared.types.extra_types import JSONObject, JSONValue


class ObsidianSaveNoteRequest(StrictSchemaModel):
    """Request to create one Alexandria-managed Obsidian note."""

    title: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Title for this Obsidian save note request."),
    ]
    body: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Body for this Obsidian save note request."),
    ]
    alexandria_type: Annotated[
        AlexandriaNoteType,
        described_field("Alexandria type for this Obsidian save note request."),
    ]
    id: Annotated[
        str | None,
        described_field("Stable identifier for this Obsidian save note request."),
    ] = None
    path: Annotated[
        str | None, described_field("Path for this Obsidian save note request.")
    ] = None
    tags: Annotated[
        list[str], described_field("Tags for this Obsidian save note request.")
    ] = schema_list_default()
    status: Annotated[
        str, described_field("Status for this Obsidian save note request.")
    ] = "active"
    project: Annotated[
        str | None, described_field("Project for this Obsidian save note request.")
    ] = None
    source: Annotated[
        str, described_field("Source for this Obsidian save note request.")
    ] = "mcp"
    frontmatter: Annotated[
        JSONObject, described_field("Frontmatter for this Obsidian save note request.")
    ] = schema_dict_default()
    expected_content_hash: Annotated[
        str | None,
        StringConstraints(
            strict=True, min_length=64, max_length=64, pattern="^[0-9a-f]{64}$"
        ),
        described_field("Expected content hash for this Obsidian save note request."),
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
        described_field("Storage status for this Obsidian write pipeline response."),
    ]
    metadata_status: Annotated[
        str,
        described_field("Metadata status for this Obsidian write pipeline response."),
    ]
    fts_status: Annotated[
        str, described_field("FTS status for this Obsidian write pipeline response.")
    ]
    graph_edge_index_status: Annotated[
        str,
        described_field(
            "Graph edge index status for this Obsidian write pipeline response."
        ),
    ]
    graph_projection_status: Annotated[
        str,
        described_field(
            "Graph projection status for this Obsidian write pipeline response."
        ),
    ]


class ObsidianNoteWriteResponse(StrictSchemaModel):
    """Explicit write outcome without overloading note index status."""

    operation: Annotated[
        ObsidianWriteOperation,
        described_field("Operation for this Obsidian note write response."),
    ]
    write_mode: Annotated[
        ObsidianWriteMode,
        described_field("Write mode for this Obsidian note write response."),
    ]
    match_by: Annotated[
        ObsidianWriteMatchBy,
        described_field("Match by for this Obsidian note write response."),
    ]
    note: Annotated[
        ObsidianNoteResponse,
        described_field("Note for this Obsidian note write response."),
    ]
    pipeline: Annotated[
        ObsidianWritePipelineResponse,
        described_field("Pipeline for this Obsidian note write response."),
    ]
    reindex_required: Annotated[
        bool, described_field("Reindex required for this Obsidian note write response.")
    ]
    warnings: Annotated[
        list[str], described_field("Warnings for this Obsidian note write response.")
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
