"""Pydantic schemas for PostgreSQL graph projection operations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionOperationError,
    ObsidianGraphProjectionRebuildReport,
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjectionIssueCount,
)
from app.shared.schemas.common_schemas import StrictSchemaModel


class ObsidianGraphProjectionOperationErrorResponse(StrictSchemaModel):
    """One graph projection operation diagnostic exposed at the API boundary."""

    code: Annotated[
        str,
        Field(
            description="Code for this Obsidian graph projection operation error response."
        ),
    ]
    relative_path: Annotated[
        str | None,
        Field(
            description="Relative path for this Obsidian graph projection operation error response."
        ),
    ] = None
    note_id: Annotated[
        str | None,
        Field(
            description="Note identifier for this Obsidian graph projection operation error response."
        ),
    ] = None
    edge_id: Annotated[
        str | None,
        Field(
            description="Edge identifier for this Obsidian graph projection operation error response."
        ),
    ] = None
    detail: Annotated[
        str | None,
        Field(
            description="Detail for this Obsidian graph projection operation error response."
        ),
    ] = None

    @classmethod
    def from_entity(
        cls,
        error: ObsidianGraphProjectionOperationError,
    ) -> ObsidianGraphProjectionOperationErrorResponse:
        """Build a response error from an internal operation diagnostic.

        Args:
            error: Internal graph projection operation diagnostic.

        Returns:
            API response model for one diagnostic.
        """
        return cls(
            code=error.code,
            relative_path=error.relative_path,
            note_id=error.note_id,
            edge_id=error.edge_id,
            detail=error.detail,
        )


class ObsidianGraphProjectionIssueCountResponse(StrictSchemaModel):
    """Counted non-fatal source diagnostic."""

    code: Annotated[
        str,
        Field(
            description="Code for this Obsidian graph projection issue count response."
        ),
    ]
    count: Annotated[
        int,
        Field(
            description="Count for this Obsidian graph projection issue count response.",
            ge=1,
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        item: ObsidianGraphProjectionIssueCount,
    ) -> ObsidianGraphProjectionIssueCountResponse:
        """Build this schema from a domain entity.

        Args:
            item: Domain item to serialize into the response schema.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(code=item.code.value, count=item.count)


class ObsidianGraphProjectionRebuildResponse(StrictSchemaModel):
    """Response body for one explicit graph projection rebuild."""

    status: Annotated[
        Literal["completed", "failed"],
        Field(
            description="Status for this Obsidian graph projection rebuild response."
        ),
    ]
    graph_read_model: Annotated[
        Literal["postgresql"],
        Field(
            description="Graph read model for this Obsidian graph projection rebuild response."
        ),
    ]
    run_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(
            description="Run identifier for this Obsidian graph projection rebuild response."
        ),
    ]
    scanned: Annotated[
        int,
        Field(
            description="Scanned for this Obsidian graph projection rebuild response.",
            ge=0,
        ),
    ]
    indexed: Annotated[
        int,
        Field(
            description="Indexed for this Obsidian graph projection rebuild response.",
            ge=0,
        ),
    ]
    updated: Annotated[
        int,
        Field(
            description="Updated for this Obsidian graph projection rebuild response.",
            ge=0,
        ),
    ]
    skipped: Annotated[
        int,
        Field(
            description="Skipped for this Obsidian graph projection rebuild response.",
            ge=0,
        ),
    ]
    issue_total: Annotated[
        int,
        Field(
            description="Issue total for this Obsidian graph projection rebuild response.",
            ge=0,
        ),
    ]
    issue_counts: Annotated[
        list[ObsidianGraphProjectionIssueCountResponse],
        Field(
            description="Issue counts for this Obsidian graph projection rebuild response."
        ),
    ]
    issues: Annotated[
        list[ObsidianGraphProjectionOperationErrorResponse],
        Field(
            description="Issues for this Obsidian graph projection rebuild response."
        ),
    ]
    issues_truncated: Annotated[
        bool,
        Field(
            description="Issues truncated for this Obsidian graph projection rebuild response."
        ),
    ]
    errors: Annotated[
        list[ObsidianGraphProjectionOperationErrorResponse],
        Field(
            description="Errors for this Obsidian graph projection rebuild response."
        ),
    ]
    duration_seconds: Annotated[
        float,
        Field(
            description="Duration seconds for this Obsidian graph projection rebuild response.",
            ge=0,
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        report: ObsidianGraphProjectionRebuildReport,
    ) -> ObsidianGraphProjectionRebuildResponse:
        """Build a response body from an internal rebuild report.

        Args:
            report: Internal rebuild operation report.

        Returns:
            API response model for the rebuild operation.
        """
        return cls(
            status=report.status,
            graph_read_model=report.graph_read_model,
            run_id=report.run_id,
            scanned=report.scanned,
            indexed=report.indexed,
            updated=report.updated,
            skipped=report.skipped,
            issue_total=report.issue_total,
            issue_counts=[
                ObsidianGraphProjectionIssueCountResponse.from_entity(item)
                for item in report.issue_counts
            ],
            issues=[
                ObsidianGraphProjectionOperationErrorResponse.from_entity(issue)
                for issue in report.issues
            ],
            issues_truncated=report.issues_truncated,
            errors=[
                ObsidianGraphProjectionOperationErrorResponse.from_entity(error)
                for error in report.errors
            ],
            duration_seconds=report.duration_seconds,
        )


class ObsidianGraphProjectionStatusResponse(StrictSchemaModel):
    """Response body for graph projection status."""

    status: Annotated[
        Literal["uninitialized", "ready", "unavailable"],
        Field(description="Status for this Obsidian graph projection status response."),
    ]
    graph_read_model: Annotated[
        Literal["postgresql"],
        Field(
            description="Graph read model for this Obsidian graph projection status response."
        ),
    ]
    enabled: Annotated[
        bool,
        Field(
            description="Whether this Obsidian graph projection status response is enabled."
        ),
    ]
    node_count: Annotated[
        int,
        Field(
            description="Node count for this Obsidian graph projection status response.",
            ge=0,
        ),
    ]
    edge_count: Annotated[
        int,
        Field(
            description="Edge count for this Obsidian graph projection status response.",
            ge=0,
        ),
    ]
    run_id: Annotated[
        str | None,
        Field(
            description="Run identifier for this Obsidian graph projection status response."
        ),
    ] = None
    projection_version: Annotated[
        int | None,
        Field(
            description="Projection version for this Obsidian graph projection status response.",
            ge=1,
        ),
    ] = None
    last_run_issue_total: Annotated[
        int,
        Field(
            description="Last run issue total for this Obsidian graph projection status response.",
            ge=0,
        ),
    ]
    last_run_issue_counts: Annotated[
        list[ObsidianGraphProjectionIssueCountResponse],
        Field(
            description="Last run issue counts for this Obsidian graph projection status response."
        ),
    ]
    errors: Annotated[
        list[ObsidianGraphProjectionOperationErrorResponse],
        Field(description="Errors for this Obsidian graph projection status response."),
    ]

    @classmethod
    def from_entity(
        cls,
        report: ObsidianGraphProjectionStatusReport,
    ) -> ObsidianGraphProjectionStatusResponse:
        """Build a response body from an internal status report.

        Args:
            report: Internal graph projection status report.

        Returns:
            API response model for graph projection status.
        """
        return cls(
            status=report.status,
            graph_read_model=report.graph_read_model,
            enabled=report.enabled,
            node_count=report.node_count,
            edge_count=report.edge_count,
            run_id=report.run_id,
            projection_version=report.projection_version,
            last_run_issue_total=report.last_run_issue_total,
            last_run_issue_counts=[
                ObsidianGraphProjectionIssueCountResponse.from_entity(item)
                for item in report.last_run_issue_counts
            ],
            errors=[
                ObsidianGraphProjectionOperationErrorResponse.from_entity(error)
                for error in report.errors
            ],
        )


class ObsidianGraphBuildStatusResponse(StrictSchemaModel):
    """Response body for graph build/status diagnostics."""

    projection: Annotated[
        ObsidianGraphProjectionStatusResponse,
        Field(description="Projection for this Obsidian graph build status response."),
    ]
    rebuild_note_graph_supported: Annotated[
        bool,
        Field(
            description="Rebuild note graph supported for this Obsidian graph build status response."
        ),
    ] = True
    validation_only_supported: Annotated[
        bool,
        Field(
            description="Validation only supported for this Obsidian graph build status response."
        ),
    ] = True
    detail: Annotated[
        str, Field(description="Detail for this Obsidian graph build status response.")
    ]

    @classmethod
    def from_status_report(
        cls,
        report: ObsidianGraphProjectionStatusReport,
    ) -> ObsidianGraphBuildStatusResponse:
        """Build graph build/status response from the projection status report.

        Args:
            report: Value supplied to from_status_report.

        Returns:
            Result produced by from_status_report.
        """
        return cls(
            projection=ObsidianGraphProjectionStatusResponse.from_entity(report),
            detail=(
                "Per-note rebuild reparses one canonical note into PostgreSQL, replaces "
                "its outgoing edges, then activates a full snapshot projection."
            ),
        )


class ObsidianGraphNoteSelectorResponse(StrictSchemaModel):
    """Exact selector echoed by per-note graph diagnostics."""

    note_id: Annotated[
        str | None,
        Field(
            description="Note identifier for this Obsidian graph note selector response."
        ),
    ] = None
    path: Annotated[
        str | None,
        Field(description="Path for this Obsidian graph note selector response."),
    ] = None
