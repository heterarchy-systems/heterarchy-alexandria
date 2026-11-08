"""HTTP schemas for safe Obsidian vault move operations."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianVaultMoveApplyRequest,
    ObsidianVaultMovePlanRequest,
    ObsidianVaultMoveRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianVaultMoveApplied,
    ObsidianVaultMoveCandidate,
    ObsidianVaultMovePlan,
    ObsidianVaultMoveReport,
    ObsidianVaultMoveSkip,
)
from app.obsidian.interface.schemas.obsidian.obsidian_string_types import (
    ObsidianPathText,
    ObsidianQueryText,
)
from app.shared.schemas.common_schemas import StrictSchemaModel


class ObsidianVaultPathSearchRequest(StrictSchemaModel):
    """Metadata/path search request for vault operation planning."""

    query: Annotated[
        ObsidianQueryText,
        Field(description="Query for this Obsidian vault path search request."),
    ]
    scope_path: Annotated[
        str | None,
        Field(description="Scope path for this Obsidian vault path search request."),
    ] = None


class ObsidianVaultMoveRequestSchema(StrictSchemaModel):
    """One requested safe vault move."""

    source_path: Annotated[
        ObsidianPathText,
        Field(description="Source path for this Obsidian vault move request."),
    ]
    destination_path: Annotated[
        ObsidianPathText,
        Field(description="Destination path for this Obsidian vault move request."),
    ]
    reason: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Reason for this Obsidian vault move request."),
    ]

    def to_command(self) -> ObsidianVaultMoveRequest:
        """Convert request into move command.

        Returns:
            Application move request.
        """
        return ObsidianVaultMoveRequest(
            source_path=self.source_path,
            destination_path=self.destination_path,
            reason=self.reason,
        )


class ObsidianVaultMovePlanRequestSchema(StrictSchemaModel):
    """Dry-run move plan request."""

    moves: Annotated[
        list[ObsidianVaultMoveRequestSchema],
        Field(
            description="Moves for this Obsidian vault move plan request.", min_length=1
        ),
    ]

    def to_command(self) -> ObsidianVaultMovePlanRequest:
        """Convert request into application plan command.

        Returns:
            Move plan request.
        """
        return ObsidianVaultMovePlanRequest(
            moves=tuple(move.to_command() for move in self.moves)
        )


class ObsidianVaultMoveApplyRequestSchema(StrictSchemaModel):
    """Safe move application request."""

    moves: Annotated[
        list[ObsidianVaultMoveRequestSchema],
        Field(
            description="Moves for this Obsidian vault move apply request.",
            min_length=1,
        ),
    ]
    report_path: Annotated[
        str | None,
        Field(description="Report path for this Obsidian vault move apply request."),
    ] = None
    reindex: Annotated[
        bool, Field(description="Reindex for this Obsidian vault move apply request.")
    ] = True
    verification_query: Annotated[
        str | None,
        Field(
            description="Verification query for this Obsidian vault move apply request."
        ),
    ] = None

    def to_command(self) -> ObsidianVaultMoveApplyRequest:
        """Convert request into application apply command.

        Returns:
            Move apply request.
        """
        return ObsidianVaultMoveApplyRequest(
            moves=tuple(move.to_command() for move in self.moves),
            report_path=self.report_path,
            reindex=self.reindex,
            verification_query=self.verification_query,
        )


class ObsidianVaultMoveCandidateResponse(StrictSchemaModel):
    """One safety-approved move candidate."""

    source_path: Annotated[
        str,
        Field(
            description="Source path for this Obsidian vault move candidate response."
        ),
    ]
    destination_path: Annotated[
        str,
        Field(
            description="Destination path for this Obsidian vault move candidate response."
        ),
    ]
    reason: Annotated[
        str,
        Field(description="Reason for this Obsidian vault move candidate response."),
    ]

    @classmethod
    def from_entity(
        cls,
        item: ObsidianVaultMoveCandidate,
    ) -> ObsidianVaultMoveCandidateResponse:
        """Create response from move candidate.

        Args:
            item: Move candidate entity.

        Returns:
            Move candidate response.
        """
        return cls(
            source_path=item.source_path,
            destination_path=item.destination_path,
            reason=item.reason,
        )


class ObsidianVaultMoveSkipResponse(StrictSchemaModel):
    """One skipped move candidate with reason."""

    source_path: Annotated[
        str,
        Field(description="Source path for this Obsidian vault move skip response."),
    ]
    destination_path: Annotated[
        str,
        Field(
            description="Destination path for this Obsidian vault move skip response."
        ),
    ]
    reason: Annotated[
        str, Field(description="Reason for this Obsidian vault move skip response.")
    ]

    @classmethod
    def from_entity(cls, item: ObsidianVaultMoveSkip) -> ObsidianVaultMoveSkipResponse:
        """Create response from skipped move.

        Args:
            item: Move skip entity.

        Returns:
            Move skip response.
        """
        return cls(
            source_path=item.source_path,
            destination_path=item.destination_path,
            reason=item.reason,
        )


class ObsidianVaultMovePlanResponse(StrictSchemaModel):
    """Dry-run move plan response."""

    status: Annotated[
        str, Field(description="Status for this Obsidian vault move plan response.")
    ]
    hard_delete_performed: Annotated[
        bool,
        Field(
            description="Hard delete performed for this Obsidian vault move plan response."
        ),
    ]
    moves: Annotated[
        list[ObsidianVaultMoveCandidateResponse],
        Field(description="Moves for this Obsidian vault move plan response."),
    ]
    skipped: Annotated[
        list[ObsidianVaultMoveSkipResponse],
        Field(description="Skipped for this Obsidian vault move plan response."),
    ]
    ambiguous: Annotated[
        list[ObsidianVaultMoveSkipResponse],
        Field(description="Ambiguous for this Obsidian vault move plan response."),
    ]

    @classmethod
    def from_entity(cls, plan: ObsidianVaultMovePlan) -> ObsidianVaultMovePlanResponse:
        """Create response from move plan.

        Args:
            plan: Move plan entity.

        Returns:
            Move plan response.
        """
        return cls(
            status=plan.status,
            hard_delete_performed=plan.hard_delete_performed,
            moves=[
                ObsidianVaultMoveCandidateResponse.from_entity(item)
                for item in plan.moves
            ],
            skipped=[
                ObsidianVaultMoveSkipResponse.from_entity(item) for item in plan.skipped
            ],
            ambiguous=[
                ObsidianVaultMoveSkipResponse.from_entity(item)
                for item in plan.ambiguous
            ],
        )


class ObsidianVaultMoveAppliedResponse(StrictSchemaModel):
    """One applied safe move."""

    source_path: Annotated[
        str,
        Field(description="Source path for this Obsidian vault move applied response."),
    ]
    destination_path: Annotated[
        str,
        Field(
            description="Destination path for this Obsidian vault move applied response."
        ),
    ]
    reason: Annotated[
        str, Field(description="Reason for this Obsidian vault move applied response.")
    ]

    @classmethod
    def from_entity(
        cls,
        item: ObsidianVaultMoveApplied,
    ) -> ObsidianVaultMoveAppliedResponse:
        """Create response from applied move.

        Args:
            item: Applied move entity.

        Returns:
            Applied move response.
        """
        return cls(
            source_path=item.source_path,
            destination_path=item.destination_path,
            reason=item.reason,
        )


class ObsidianVaultMoveVerificationResponse(StrictSchemaModel):
    """Verification summary after move application."""

    source_root_loose_notes_remaining: Annotated[
        int,
        Field(
            description="Source root loose notes remaining for this Obsidian vault move verification response."
        ),
    ]
    reindex_status: Annotated[
        str,
        Field(
            description="Reindex status for this Obsidian vault move verification response."
        ),
    ]
    verification_hits: Annotated[
        int,
        Field(
            description="Verification hits for this Obsidian vault move verification response."
        ),
    ]


class ObsidianVaultMoveReportResponse(StrictSchemaModel):
    """Safe move application report response."""

    status: Annotated[
        str, Field(description="Status for this Obsidian vault move report response.")
    ]
    hard_delete_performed: Annotated[
        bool,
        Field(
            description="Hard delete performed for this Obsidian vault move report response."
        ),
    ]
    moved: Annotated[
        list[ObsidianVaultMoveAppliedResponse],
        Field(description="Moved for this Obsidian vault move report response."),
    ]
    skipped: Annotated[
        list[ObsidianVaultMoveSkipResponse],
        Field(description="Skipped for this Obsidian vault move report response."),
    ]
    ambiguous: Annotated[
        list[ObsidianVaultMoveSkipResponse],
        Field(description="Ambiguous for this Obsidian vault move report response."),
    ]
    verification: Annotated[
        ObsidianVaultMoveVerificationResponse,
        Field(description="Verification for this Obsidian vault move report response."),
    ]
    report_markdown_path: Annotated[
        str,
        Field(
            description="Report markdown path for this Obsidian vault move report response."
        ),
    ]
    report_json_path: Annotated[
        str,
        Field(
            description="Report JSON path for this Obsidian vault move report response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        report: ObsidianVaultMoveReport,
    ) -> ObsidianVaultMoveReportResponse:
        """Create response from move report.

        Args:
            report: Move report entity.

        Returns:
            Move report response.
        """
        return cls(
            status=report.status,
            hard_delete_performed=report.hard_delete_performed,
            moved=[
                ObsidianVaultMoveAppliedResponse.from_entity(item)
                for item in report.moved
            ],
            skipped=[
                ObsidianVaultMoveSkipResponse.from_entity(item)
                for item in report.skipped
            ],
            ambiguous=[
                ObsidianVaultMoveSkipResponse.from_entity(item)
                for item in report.ambiguous
            ],
            verification=ObsidianVaultMoveVerificationResponse(
                source_root_loose_notes_remaining=(
                    report.verification.source_root_loose_notes_remaining
                ),
                reindex_status=report.verification.reindex_status,
                verification_hits=report.verification.verification_hits,
            ),
            report_markdown_path=report.report_markdown_path,
            report_json_path=report.report_json_path,
        )
