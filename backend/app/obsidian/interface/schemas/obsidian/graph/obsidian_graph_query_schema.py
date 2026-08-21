"""Obsidian graph query schema contracts."""

from __future__ import annotations

from typing import Annotated

from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_support import (
    ObsidianGraphNoteLinkValidationReport,
    ObsidianGraphNoteRebuildReport,
)
from app.obsidian.interface.schemas.obsidian.graph.obsidian_graph_projection_schema import (
    ObsidianGraphNoteSelectorResponse,
    ObsidianGraphProjectionRebuildResponse,
    ObsidianGraphProjectionStatusResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class ObsidianGraphNoteIndexDiagnosticResponse(StrictSchemaModel):
    """Indexed-note existence and projection eligibility."""

    exists: Annotated[
        bool,
        described_field(
            "Exists for this Obsidian graph note index diagnostic response."
        ),
    ]
    note_id: Annotated[
        str | None,
        described_field(
            "Note identifier for this Obsidian graph note index diagnostic response."
        ),
    ] = None
    relative_path: Annotated[
        str | None,
        described_field(
            "Relative path for this Obsidian graph note index diagnostic response."
        ),
    ] = None
    title: Annotated[
        str | None,
        described_field(
            "Title for this Obsidian graph note index diagnostic response."
        ),
    ] = None
    index_status: Annotated[
        str | None,
        described_field(
            "Index status for this Obsidian graph note index diagnostic response."
        ),
    ] = None
    error_message: Annotated[
        str | None,
        described_field(
            "Error message for this Obsidian graph note index diagnostic response."
        ),
    ] = None
    projection_included: Annotated[
        bool,
        described_field(
            "Projection included for this Obsidian graph note index diagnostic response."
        ),
    ]


class ObsidianGraphResolvedTargetResponse(StrictSchemaModel):
    """One outgoing edge resolved to a healthy indexed target."""

    edge_id: Annotated[
        str,
        described_field(
            "Edge identifier for this Obsidian graph resolved target response."
        ),
    ]
    target_note_id: Annotated[
        str,
        described_field(
            "Target note identifier for this Obsidian graph resolved target response."
        ),
    ]
    target_path: Annotated[
        str,
        described_field(
            "Target path for this Obsidian graph resolved target response."
        ),
    ]
    relation: Annotated[
        str,
        described_field("Relation for this Obsidian graph resolved target response."),
    ]
    source_kind: Annotated[
        str,
        described_field(
            "Source kind for this Obsidian graph resolved target response."
        ),
    ]


class ObsidianGraphUnresolvedTargetResponse(StrictSchemaModel):
    """One outgoing edge target that cannot be projected cleanly."""

    edge_id: Annotated[
        str,
        described_field(
            "Edge identifier for this Obsidian graph unresolved target response."
        ),
    ]
    target_path: Annotated[
        str,
        described_field(
            "Target path for this Obsidian graph unresolved target response."
        ),
    ]
    relation: Annotated[
        str,
        described_field("Relation for this Obsidian graph unresolved target response."),
    ]
    source_kind: Annotated[
        str,
        described_field(
            "Source kind for this Obsidian graph unresolved target response."
        ),
    ]
    code: Annotated[
        str, described_field("Code for this Obsidian graph unresolved target response.")
    ]
    detail: Annotated[
        str,
        described_field("Detail for this Obsidian graph unresolved target response."),
    ]
    target_note_id: Annotated[
        str | None,
        described_field(
            "Target note identifier for this Obsidian graph unresolved target response."
        ),
    ] = None
    candidate_note_ids: Annotated[
        list[str],
        described_field(
            "Candidate note identifiers for this Obsidian graph unresolved target response."
        ),
    ]
    candidate_paths: Annotated[
        list[str],
        described_field(
            "Candidate paths for this Obsidian graph unresolved target response."
        ),
    ]


class ObsidianGraphOutgoingLinkDiagnosticResponse(StrictSchemaModel):
    """Counts and details for outgoing graph edges from one note."""

    parsed_count: Annotated[
        int,
        described_field(
            "Parsed count for this Obsidian graph outgoing link diagnostic response.",
            ge=0,
        ),
    ]
    resolved_count: Annotated[
        int,
        described_field(
            "Resolved count for this Obsidian graph outgoing link diagnostic response.",
            ge=0,
        ),
    ]
    unresolved_count: Annotated[
        int,
        described_field(
            "Unresolved count for this Obsidian graph outgoing link diagnostic response.",
            ge=0,
        ),
    ]
    unresolved_targets: Annotated[
        list[ObsidianGraphUnresolvedTargetResponse],
        described_field(
            "Unresolved targets for this Obsidian graph outgoing link diagnostic response."
        ),
    ]
    resolved_targets: Annotated[
        list[ObsidianGraphResolvedTargetResponse],
        described_field(
            "Resolved targets for this Obsidian graph outgoing link diagnostic response."
        ),
    ]


class ObsidianGraphNoteLinkValidationResponse(StrictSchemaModel):
    """Response body for per-note graph link validation."""

    selector: Annotated[
        ObsidianGraphNoteSelectorResponse,
        described_field(
            "Selector for this Obsidian graph note link validation response."
        ),
    ]
    note: Annotated[
        ObsidianGraphNoteIndexDiagnosticResponse,
        described_field("Note for this Obsidian graph note link validation response."),
    ]
    outgoing: Annotated[
        ObsidianGraphOutgoingLinkDiagnosticResponse,
        described_field(
            "Outgoing for this Obsidian graph note link validation response."
        ),
    ]
    projection: Annotated[
        ObsidianGraphProjectionStatusResponse,
        described_field(
            "Projection for this Obsidian graph note link validation response."
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
        described_field(
            "Replace existing edges for this Obsidian graph note rebuild response."
        ),
    ]
    validation: Annotated[
        ObsidianGraphNoteLinkValidationResponse,
        described_field("Validation for this Obsidian graph note rebuild response."),
    ]
    projection: Annotated[
        ObsidianGraphProjectionRebuildResponse,
        described_field("Projection for this Obsidian graph note rebuild response."),
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
