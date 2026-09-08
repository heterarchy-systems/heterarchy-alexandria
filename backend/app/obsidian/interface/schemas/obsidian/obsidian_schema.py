"""HTTP schemas for Obsidian vault operations."""

from __future__ import annotations

from typing import Annotated

from app.obsidian.application.service.vault.obsidian_vault_reindex_service import (
    ObsidianVaultReindexReport,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianNote,
    ObsidianReindexResult,
    ObsidianVaultStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexErrorCode,
    ObsidianIndexStatus,
)
from app.obsidian.interface.schemas.obsidian.graph.obsidian_graph_projection_schema import (
    ObsidianGraphProjectionRebuildResponse,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_dict_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONObject


class ObsidianStatusResponse(StrictSchemaModel):
    """Current Obsidian vault/index status."""

    vault_path: Annotated[
        str, described_field("Vault path for this Obsidian status response.")
    ]
    alexandria_root: Annotated[
        str, described_field("Alexandria root for this Obsidian status response.")
    ]
    vault_exists: Annotated[
        bool, described_field("Vault exists for this Obsidian status response.")
    ]
    alexandria_root_exists: Annotated[
        bool,
        described_field("Alexandria root exists for this Obsidian status response."),
    ]
    indexed_notes: Annotated[
        int, described_field("Indexed notes for this Obsidian status response.")
    ]
    stale_notes: Annotated[
        int, described_field("Stale notes for this Obsidian status response.")
    ]
    error_notes: Annotated[
        int, described_field("Error notes for this Obsidian status response.")
    ]
    index_errors: Annotated[
        list[ObsidianIndexErrorResponse],
        described_field("Index errors for this Obsidian status response."),
    ]

    @classmethod
    def from_entity(cls, status: ObsidianVaultStatus) -> ObsidianStatusResponse:
        """Create schema from entity.

        Args:
            status: Domain status entity.

        Returns:
            HTTP response schema.
        """
        return cls(
            vault_path=status.vault_path,
            alexandria_root=status.alexandria_root,
            vault_exists=status.vault_exists,
            alexandria_root_exists=status.alexandria_root_exists,
            indexed_notes=status.indexed_notes,
            stale_notes=status.stale_notes,
            error_notes=status.error_notes,
            index_errors=[
                ObsidianIndexErrorResponse.from_entity(error)
                for error in status.index_errors
            ],
        )


class ObsidianIndexErrorResponse(StrictSchemaModel):
    """Structured note-index failure returned to operators."""

    note_path: Annotated[
        str, described_field("Note path for this Obsidian index error response.")
    ]
    context_id: Annotated[
        str | None,
        described_field("Context identifier for this Obsidian index error response."),
    ]
    error_code: Annotated[
        ObsidianIndexErrorCode,
        described_field("Error code for this Obsidian index error response."),
    ]
    error_message: Annotated[
        str, described_field("Error message for this Obsidian index error response.")
    ]
    detected_at: Annotated[
        AwareTimestamp,
        described_field("Detected at for this Obsidian index error response."),
    ]

    @classmethod
    def from_entity(cls, error: ObsidianIndexError) -> ObsidianIndexErrorResponse:
        """Build this schema from a domain entity.

        Args:
            error: Error details captured for the response or report.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(
            note_path=error.note_path,
            context_id=error.context_id,
            error_code=error.error_code,
            error_message=error.error_message,
            detected_at=error.detected_at,
        )


class ObsidianReindexResponse(StrictSchemaModel):
    """Vault reindex response."""

    files_seen: Annotated[
        int, described_field("Files seen for this Obsidian reindex response.")
    ]
    files_indexed: Annotated[
        int, described_field("Files indexed for this Obsidian reindex response.")
    ]
    files_skipped: Annotated[
        int, described_field("Files skipped for this Obsidian reindex response.")
    ]
    stale_marked: Annotated[
        int, described_field("Stale marked for this Obsidian reindex response.")
    ]
    errors: Annotated[
        list[str], described_field("Errors for this Obsidian reindex response.")
    ]
    error_details: Annotated[
        list[ObsidianIndexErrorResponse],
        described_field("Error details for this Obsidian reindex response."),
    ]
    skip_reasons: Annotated[
        dict[str, int],
        described_field("Skip reasons for this Obsidian reindex response."),
    ] = schema_dict_default()
    edge_targets_resolved: Annotated[
        int,
        described_field("Edge targets resolved for this Obsidian reindex response."),
    ] = 0
    graph_projection: Annotated[
        ObsidianGraphProjectionRebuildResponse | None,
        described_field("Graph projection for this Obsidian reindex response."),
    ] = None

    @classmethod
    def from_entity(cls, result: ObsidianReindexResult) -> ObsidianReindexResponse:
        """Create schema from entity.

        Args:
            result: Domain reindex result.

        Returns:
            HTTP response schema.
        """
        return cls(
            files_seen=result.files_seen,
            files_indexed=result.files_indexed,
            files_skipped=result.files_skipped,
            stale_marked=result.stale_marked,
            errors=list(result.errors),
            error_details=[
                ObsidianIndexErrorResponse.from_entity(error)
                for error in result.error_details
            ],
            skip_reasons=result.skip_reasons,
            edge_targets_resolved=result.edge_targets_resolved,
        )

    @classmethod
    def from_reindex_report(
        cls,
        report: ObsidianVaultReindexReport,
    ) -> ObsidianReindexResponse:
        """Create schema from a public composite reindex report.

        Args:
            report: Combined PostgreSQL and PostgreSQL graph projection report.

        Returns:
            HTTP response schema with fresh graph projection evidence.
        """
        result = report.vault_index
        return cls(
            files_seen=result.files_seen,
            files_indexed=result.files_indexed,
            files_skipped=result.files_skipped,
            stale_marked=result.stale_marked,
            errors=list(result.errors),
            error_details=[
                ObsidianIndexErrorResponse.from_entity(error)
                for error in result.error_details
            ],
            skip_reasons=result.skip_reasons,
            edge_targets_resolved=result.edge_targets_resolved,
            graph_projection=ObsidianGraphProjectionRebuildResponse.from_entity(
                report.graph_projection
            ),
        )


class ObsidianNoteResponse(StrictSchemaModel):
    """One indexed Obsidian note response."""

    id: Annotated[
        str, described_field("Stable identifier for this Obsidian note response.")
    ]
    alexandria_type: Annotated[
        AlexandriaNoteType,
        described_field("Alexandria type for this Obsidian note response."),
    ]
    path: Annotated[str, described_field("Path for this Obsidian note response.")]
    title: Annotated[str, described_field("Title for this Obsidian note response.")]
    status: Annotated[str, described_field("Status for this Obsidian note response.")]
    tags: Annotated[list[str], described_field("Tags for this Obsidian note response.")]
    project: Annotated[
        str | None, described_field("Project for this Obsidian note response.")
    ]
    source: Annotated[
        str | None, described_field("Source for this Obsidian note response.")
    ]
    content_hash: Annotated[
        str, described_field("Content hash for this Obsidian note response.")
    ]
    frontmatter: Annotated[
        JSONObject, described_field("Frontmatter for this Obsidian note response.")
    ]
    body: Annotated[str, described_field("Body for this Obsidian note response.")]
    index_status: Annotated[
        ObsidianIndexStatus,
        described_field("Index status for this Obsidian note response."),
    ]
    error_message: Annotated[
        str | None, described_field("Error message for this Obsidian note response.")
    ]
    size_bytes: Annotated[
        int, described_field("Size bytes for this Obsidian note response.")
    ]
    modified_at: Annotated[
        AwareTimestamp, described_field("Modified at for this Obsidian note response.")
    ]
    indexed_at: Annotated[
        AwareTimestamp | None,
        described_field("Indexed at for this Obsidian note response."),
    ]
    wikilink: Annotated[
        str, described_field("Wikilink for this Obsidian note response.")
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
