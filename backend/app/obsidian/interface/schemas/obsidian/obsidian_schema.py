"""HTTP schemas for Obsidian vault operations."""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, StringConstraints

from app.obsidian.application.service.vault.obsidian_vault_reindex_service import (
    ObsidianVaultReindexReport,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianNote,
    ObsidianNoteRawRead,
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
    schema_list_default,
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


class ObsidianNoteRepairRequest(StrictSchemaModel):
    """Bounded raw-source repair for one malformed or damaged note."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=400),
        described_field("Vault-relative path for this note repair request."),
    ]
    expected_content_hash: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
        described_field("Expected content hash for this note repair request."),
    ]
    raw_content: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Full replacement Markdown source for this repair."),
    ]


class ObsidianNoteRawReadResponse(StrictSchemaModel):
    """Raw malformed-note read response for operator repair inspection."""

    relative_path: Annotated[
        str, described_field("Path for this Obsidian note raw read response.")
    ]
    raw_text: Annotated[
        str | None,
        described_field("Raw text for this Obsidian note raw read response."),
    ]
    content_hash: Annotated[
        str | None,
        described_field("Content hash for this Obsidian note raw read response."),
    ]
    byte_length: Annotated[
        int | None,
        described_field("Byte length for this Obsidian note raw read response."),
    ]
    parse_status: Annotated[
        str,
        described_field("Parse status for this Obsidian note raw read response."),
    ]
    parse_error: Annotated[
        str | None,
        described_field("Parse error for this Obsidian note raw read response."),
    ]
    frontmatter: Annotated[
        JSONObject | None,
        described_field("Frontmatter for this Obsidian note raw read response."),
    ]
    body: Annotated[
        str | None, described_field("Body for this Obsidian note raw read response.")
    ]
    note_id: Annotated[
        str | None,
        described_field("Note id for this Obsidian note raw read response."),
    ]
    index_status: Annotated[
        str | None,
        described_field("Index status for this Obsidian note raw read response."),
    ]

    @classmethod
    def from_entity(cls, read: ObsidianNoteRawRead) -> ObsidianNoteRawReadResponse:
        """Create schema from entity.

        Args:
            read: Domain raw read entity.

        Returns:
            HTTP response schema.
        """
        return cls(
            relative_path=read.relative_path,
            raw_text=read.raw_text,
            content_hash=read.content_hash,
            byte_length=read.byte_length,
            parse_status=read.parse_status,
            parse_error=read.parse_error,
            frontmatter=read.frontmatter,
            body=read.body,
            note_id=read.note_id,
            index_status=read.index_status,
        )


class ObsidianBatchReadSelectorRequest(StrictSchemaModel):
    """One selector in a batch read request."""

    path: Annotated[str | None, described_field("Vault-relative path selector.")] = None
    note_id: Annotated[str | None, described_field("Stable note id selector.")] = None


class ObsidianBatchReadRequest(StrictSchemaModel):
    """Batch read request with independent exact selectors."""

    selectors: Annotated[
        list[ObsidianBatchReadSelectorRequest],
        described_field("Exact per-item selectors; each needs path or note_id."),
    ] = schema_list_default()


class ObsidianBatchReadResponse(StrictSchemaModel):
    """Batch read response with per-item results."""

    items: Annotated[
        list[ObsidianNoteResponse],
        described_field("Successfully read notes in selector order."),
    ] = schema_list_default()
    errors: Annotated[
        list[dict[str, str | None]],
        described_field("Per-item errors for selectors that failed."),
    ] = schema_list_default()
    total: Annotated[int, described_field("Total selectors processed.")]


class ObsidianBatchValidateLinkItem(StrictSchemaModel):
    """Per-item link validation outcome."""

    path: Annotated[str | None, described_field("Vault-relative path.")] = None
    note_id: Annotated[str | None, described_field("Stable note id.")] = None
    status: Annotated[str, described_field("validated / not_found.")]
    exists: Annotated[bool, described_field("Whether the note exists.")] = False
    parsed_count: Annotated[int, described_field("Outgoing edge count.")] = 0
    resolved_count: Annotated[int, described_field("Resolved edge count.")] = 0
    unresolved_count: Annotated[int, described_field("Unresolved edge count.")] = 0


class ObsidianBatchValidateLinksRequest(StrictSchemaModel):
    """Batch outgoing-link validation request with exact selectors."""

    selectors: Annotated[
        list[ObsidianBatchReadSelectorRequest],
        described_field("Exact per-item selectors; each needs path or note_id."),
    ] = schema_list_default()


class ObsidianBatchValidateLinksResponse(StrictSchemaModel):
    """Batch link validation response."""

    items: Annotated[
        list[ObsidianBatchValidateLinkItem],
        described_field("Per-item validation outcomes."),
    ] = schema_list_default()


class ObsidianBatchWriteOperationRequest(StrictSchemaModel):
    """One CAS write operation in a batch."""

    op: Annotated[str, described_field("Operation type: create or update.")]
    title: Annotated[str, described_field("Note title.")]
    body: Annotated[str, described_field("Note body content.")]
    relative_path: Annotated[str, described_field("Vault-relative path.")]
    note_id: Annotated[str | None, described_field("Stable note id.")] = None
    expected_content_hash: Annotated[
        str | None, described_field("CAS content hash for update.")
    ] = None
    frontmatter: Annotated[
        JSONObject, described_field("Frontmatter key-value pairs.")
    ] = schema_dict_default()


class ObsidianBatchWriteRequest(StrictSchemaModel):
    """Batch CAS write request with independent operations."""

    operations: Annotated[
        list[ObsidianBatchWriteOperationRequest],
        described_field("Independent per-item write operations."),
    ] = schema_list_default()


class ObsidianBatchWriteItemResult(StrictSchemaModel):
    """Per-item write outcome."""

    relative_path: Annotated[str, described_field("Vault-relative path.")]
    note_id: Annotated[str | None, described_field("Stable note id.")] = None
    status: Annotated[str, described_field("Operation outcome status.")]
    content_hash: Annotated[
        str | None, described_field("Content hash after write.")
    ] = None
    current_content_hash: Annotated[
        str | None,
        described_field("Conflicting note content hash to retry CAS against."),
    ] = None
    error: Annotated[str | None, described_field("Error detail.")] = None


class ObsidianBatchWriteResponse(StrictSchemaModel):
    """Batch write response with per-item CAS results."""

    results: Annotated[
        list[ObsidianBatchWriteItemResult],
        described_field("Per-item write outcomes in request order."),
    ] = schema_list_default()
    succeeded: Annotated[int, described_field("Successful write count.")] = 0
    conflicted: Annotated[int, described_field("CAS conflict count.")] = 0
    failed: Annotated[int, described_field("Failed item count.")] = 0
