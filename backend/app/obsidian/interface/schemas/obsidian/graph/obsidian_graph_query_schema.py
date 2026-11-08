"""Obsidian graph query schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_support import (
    ObsidianGraphNoteLinkValidationReport,
    ObsidianGraphNoteRebuildReport,
)
from app.obsidian.domain.contracts.obsidian_graph_issue_contracts import (
    ObsidianGraphIssueDetail,
    ObsidianGraphIssueListResult,
)
from app.obsidian.interface.schemas.obsidian.graph.obsidian_graph_projection_schema import (
    ObsidianGraphNoteSelectorResponse,
    ObsidianGraphProjectionRebuildResponse,
    ObsidianGraphProjectionStatusResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default


class ObsidianGraphNoteIndexDiagnosticResponse(StrictSchemaModel):
    """Indexed-note existence and projection eligibility."""

    exists: Annotated[
        bool,
        Field(
            description="Exists for this Obsidian graph note index diagnostic response."
        ),
    ]
    note_id: Annotated[
        str | None,
        Field(
            description="Note identifier for this Obsidian graph note index diagnostic response."
        ),
    ] = None
    relative_path: Annotated[
        str | None,
        Field(
            description="Relative path for this Obsidian graph note index diagnostic response."
        ),
    ] = None
    title: Annotated[
        str | None,
        Field(
            description="Title for this Obsidian graph note index diagnostic response."
        ),
    ] = None
    index_status: Annotated[
        str | None,
        Field(
            description="Index status for this Obsidian graph note index diagnostic response."
        ),
    ] = None
    error_message: Annotated[
        str | None,
        Field(
            description="Error message for this Obsidian graph note index diagnostic response."
        ),
    ] = None
    projection_included: Annotated[
        bool,
        Field(
            description="Projection included for this Obsidian graph note index diagnostic response."
        ),
    ]


class ObsidianGraphResolvedTargetResponse(StrictSchemaModel):
    """One outgoing edge resolved to a healthy indexed target."""

    edge_id: Annotated[
        str,
        Field(
            description="Edge identifier for this Obsidian graph resolved target response."
        ),
    ]
    target_note_id: Annotated[
        str,
        Field(
            description="Target note identifier for this Obsidian graph resolved target response."
        ),
    ]
    target_path: Annotated[
        str,
        Field(
            description="Target path for this Obsidian graph resolved target response."
        ),
    ]
    relation: Annotated[
        str,
        Field(description="Relation for this Obsidian graph resolved target response."),
    ]
    source_kind: Annotated[
        str,
        Field(
            description="Source kind for this Obsidian graph resolved target response."
        ),
    ]


class ObsidianGraphUnresolvedTargetResponse(StrictSchemaModel):
    """One outgoing edge target that cannot be projected cleanly."""

    edge_id: Annotated[
        str,
        Field(
            description="Edge identifier for this Obsidian graph unresolved target response."
        ),
    ]
    target_path: Annotated[
        str,
        Field(
            description="Target path for this Obsidian graph unresolved target response."
        ),
    ]
    relation: Annotated[
        str,
        Field(
            description="Relation for this Obsidian graph unresolved target response."
        ),
    ]
    source_kind: Annotated[
        str,
        Field(
            description="Source kind for this Obsidian graph unresolved target response."
        ),
    ]
    code: Annotated[
        str,
        Field(description="Code for this Obsidian graph unresolved target response."),
    ]
    detail: Annotated[
        str,
        Field(description="Detail for this Obsidian graph unresolved target response."),
    ]
    target_note_id: Annotated[
        str | None,
        Field(
            description="Target note identifier for this Obsidian graph unresolved target response."
        ),
    ] = None
    candidate_note_ids: Annotated[
        list[str],
        Field(
            description="Candidate note identifiers for this Obsidian graph unresolved target response."
        ),
    ]
    candidate_paths: Annotated[
        list[str],
        Field(
            description="Candidate paths for this Obsidian graph unresolved target response."
        ),
    ]


class ObsidianGraphOutgoingLinkDiagnosticResponse(StrictSchemaModel):
    """Counts and details for outgoing graph edges from one note."""

    parsed_count: Annotated[
        int,
        Field(
            description="Parsed count for this Obsidian graph outgoing link diagnostic response.",
            ge=0,
        ),
    ]
    resolved_count: Annotated[
        int,
        Field(
            description="Resolved count for this Obsidian graph outgoing link diagnostic response.",
            ge=0,
        ),
    ]
    unresolved_count: Annotated[
        int,
        Field(
            description="Unresolved count for this Obsidian graph outgoing link diagnostic response.",
            ge=0,
        ),
    ]
    unresolved_targets: Annotated[
        list[ObsidianGraphUnresolvedTargetResponse],
        Field(
            description="Unresolved targets for this Obsidian graph outgoing link diagnostic response."
        ),
    ]
    resolved_targets: Annotated[
        list[ObsidianGraphResolvedTargetResponse],
        Field(
            description="Resolved targets for this Obsidian graph outgoing link diagnostic response."
        ),
    ]


class ObsidianGraphNoteLinkValidationResponse(StrictSchemaModel):
    """Response body for per-note graph link validation."""

    selector: Annotated[
        ObsidianGraphNoteSelectorResponse,
        Field(
            description="Selector for this Obsidian graph note link validation response."
        ),
    ]
    note: Annotated[
        ObsidianGraphNoteIndexDiagnosticResponse,
        Field(
            description="Note for this Obsidian graph note link validation response."
        ),
    ]
    outgoing: Annotated[
        ObsidianGraphOutgoingLinkDiagnosticResponse,
        Field(
            description="Outgoing for this Obsidian graph note link validation response."
        ),
    ]
    projection: Annotated[
        ObsidianGraphProjectionStatusResponse,
        Field(
            description="Projection for this Obsidian graph note link validation response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        report: ObsidianGraphNoteLinkValidationReport,
    ) -> ObsidianGraphNoteLinkValidationResponse:
        """Build response body from the internal per-note diagnostics report.

        Args:
            report: Value supplied to from_entity.

        Returns:
            Result produced by from_entity.
        """
        return cls(
            selector=ObsidianGraphNoteSelectorResponse(
                note_id=report.selector.note_id,
                path=report.selector.path,
            ),
            note=ObsidianGraphNoteIndexDiagnosticResponse(
                exists=report.note.exists,
                note_id=report.note.note_id,
                relative_path=report.note.relative_path,
                title=report.note.title,
                index_status=report.note.index_status,
                error_message=report.note.error_message,
                projection_included=report.note.projection_included,
            ),
            outgoing=ObsidianGraphOutgoingLinkDiagnosticResponse(
                parsed_count=report.outgoing.parsed_count,
                resolved_count=report.outgoing.resolved_count,
                unresolved_count=report.outgoing.unresolved_count,
                unresolved_targets=[
                    ObsidianGraphUnresolvedTargetResponse(
                        edge_id=target.edge_id,
                        target_note_id=target.target_note_id,
                        target_path=target.target_path,
                        relation=target.relation,
                        source_kind=target.source_kind,
                        code=target.code,
                        detail=target.detail,
                        candidate_note_ids=list(target.candidate_note_ids),
                        candidate_paths=list(target.candidate_paths),
                    )
                    for target in report.outgoing.unresolved_targets
                ],
                resolved_targets=[
                    ObsidianGraphResolvedTargetResponse(
                        edge_id=target.edge_id,
                        target_note_id=target.target_note_id,
                        target_path=target.target_path,
                        relation=target.relation,
                        source_kind=target.source_kind,
                    )
                    for target in report.outgoing.resolved_targets
                ],
            ),
            projection=ObsidianGraphProjectionStatusResponse.from_entity(
                report.projection_status
            ),
        )


class ObsidianGraphNoteRebuildResponse(StrictSchemaModel):
    """Response for focused indexed-edge refresh plus projection activation."""

    replace_existing_edges: Annotated[
        bool,
        Field(
            description="Replace existing edges for this Obsidian graph note rebuild response."
        ),
    ]
    validation: Annotated[
        ObsidianGraphNoteLinkValidationResponse,
        Field(description="Validation for this Obsidian graph note rebuild response."),
    ]
    projection: Annotated[
        ObsidianGraphProjectionRebuildResponse,
        Field(description="Projection for this Obsidian graph note rebuild response."),
    ]

    @classmethod
    def from_entity(
        cls,
        report: ObsidianGraphNoteRebuildReport,
    ) -> ObsidianGraphNoteRebuildResponse:
        """Create a public response from one note graph rebuild report.

        Args:
            report: Value supplied to from_entity.

        Returns:
            Result produced by from_entity.
        """
        return cls(
            replace_existing_edges=report.replace_existing_edges,
            validation=ObsidianGraphNoteLinkValidationResponse.from_entity(
                report.validation
            ),
            projection=ObsidianGraphProjectionRebuildResponse.from_entity(
                report.projection
            ),
        )


class ObsidianGraphIssueDetailResponse(StrictSchemaModel):
    """One graph projection issue with exact source and target detail."""

    issue_id: Annotated[
        str,
        Field(
            description="Stable deterministic issue identity, stable across projection runs."
        ),
    ]
    code: Annotated[str, Field(description="Graph projection issue code.")]
    edge_id: Annotated[str, Field(description="Canonical edge identifier.")]
    source_note_id: Annotated[
        str, Field(description="Source note identifier of the broken link.")
    ]
    source_path: Annotated[str, Field(description="Source note vault-relative path.")]
    source_title: Annotated[
        str | None, Field(description="Source note title when known.")
    ] = None
    target_path: Annotated[
        str, Field(description="Unresolved or ambiguous target path.")
    ]
    relation: Annotated[str, Field(description="Edge relation name.")]
    detail: Annotated[str | None, Field(description="Bounded diagnostic detail.")] = (
        None
    )
    projection_run_id: Annotated[
        str | None,
        Field(description="Projection run that produced the issue."),
    ] = None

    @classmethod
    def from_entity(
        cls,
        entity: ObsidianGraphIssueDetail,
    ) -> ObsidianGraphIssueDetailResponse:
        """Map one issue detail entity to the HTTP contract."""
        return cls(
            issue_id=entity.issue_id,
            code=entity.code,
            edge_id=entity.edge_id,
            source_note_id=entity.source_note_id,
            source_path=entity.source_path,
            source_title=entity.source_title,
            target_path=entity.target_path,
            relation=entity.relation,
            detail=entity.detail,
            projection_run_id=entity.projection_run_id,
        )


class ObsidianGraphIssueListResponse(StrictSchemaModel):
    """One bounded page of graph projection issues."""

    issues: Annotated[
        list[ObsidianGraphIssueDetailResponse],
        Field(description="Issues in edge-id order for this page."),
    ] = schema_list_default()
    next_cursor: Annotated[
        str | None,
        Field(description="Cursor for the next page; None when exhausted."),
    ] = None
    run_id: Annotated[
        str | None,
        Field(description="Projection run id backing this issue listing."),
    ] = None

    @classmethod
    def from_entity(
        cls,
        entity: ObsidianGraphIssueListResult,
    ) -> ObsidianGraphIssueListResponse:
        """Map an issue list result to the HTTP contract."""
        return cls(
            issues=[
                ObsidianGraphIssueDetailResponse.from_entity(item)
                for item in entity.issues
            ],
            next_cursor=entity.next_cursor,
            run_id=entity.run_id,
        )
