"""HTTP schemas for Obsidian vault operations."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.obsidian.application.service.vault.obsidian_vault_reindex_service import (
    ObsidianVaultReindexReport,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianReindexResult,
    ObsidianVaultStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexErrorCode
from app.obsidian.interface.schemas.obsidian.graph.obsidian_graph_projection_schema import (
    ObsidianGraphProjectionRebuildResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_dict_default
from app.shared.schemas.datetime_schemas import AwareTimestamp


class ObsidianStatusResponse(StrictSchemaModel):
    """Current Obsidian vault/index status."""

    vault_path: Annotated[
        str, Field(description="Vault path for this Obsidian status response.")
    ]
    alexandria_root: Annotated[
        str, Field(description="Alexandria root for this Obsidian status response.")
    ]
    vault_exists: Annotated[
        bool, Field(description="Vault exists for this Obsidian status response.")
    ]
    alexandria_root_exists: Annotated[
        bool,
        Field(description="Alexandria root exists for this Obsidian status response."),
    ]
    indexed_notes: Annotated[
        int, Field(description="Indexed notes for this Obsidian status response.")
    ]
    stale_notes: Annotated[
        int, Field(description="Stale notes for this Obsidian status response.")
    ]
    error_notes: Annotated[
        int, Field(description="Error notes for this Obsidian status response.")
    ]
    index_errors: Annotated[
        list[ObsidianIndexErrorResponse],
        Field(description="Index errors for this Obsidian status response."),
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
        str, Field(description="Note path for this Obsidian index error response.")
    ]
    context_id: Annotated[
        str | None,
        Field(description="Context identifier for this Obsidian index error response."),
    ]
    error_code: Annotated[
        ObsidianIndexErrorCode,
        Field(description="Error code for this Obsidian index error response."),
    ]
    error_message: Annotated[
        str, Field(description="Error message for this Obsidian index error response.")
    ]
    detected_at: Annotated[
        AwareTimestamp,
        Field(description="Detected at for this Obsidian index error response."),
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
        int, Field(description="Files seen for this Obsidian reindex response.")
    ]
    files_indexed: Annotated[
        int, Field(description="Files indexed for this Obsidian reindex response.")
    ]
    files_skipped: Annotated[
        int, Field(description="Files skipped for this Obsidian reindex response.")
    ]
    stale_marked: Annotated[
        int, Field(description="Stale marked for this Obsidian reindex response.")
    ]
    errors: Annotated[
        list[str], Field(description="Errors for this Obsidian reindex response.")
    ]
    error_details: Annotated[
        list[ObsidianIndexErrorResponse],
        Field(description="Error details for this Obsidian reindex response."),
    ]
    skip_reasons: Annotated[
        dict[str, int],
        Field(description="Skip reasons for this Obsidian reindex response."),
    ] = schema_dict_default()
    edge_targets_resolved: Annotated[
        int,
        Field(description="Edge targets resolved for this Obsidian reindex response."),
    ] = 0
    graph_projection: Annotated[
        ObsidianGraphProjectionRebuildResponse | None,
        Field(description="Graph projection for this Obsidian reindex response."),
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
