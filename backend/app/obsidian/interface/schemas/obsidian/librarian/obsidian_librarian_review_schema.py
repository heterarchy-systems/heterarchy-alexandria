"""HTTP schemas for Obsidian librarian review operations."""

from __future__ import annotations

from typing import Annotated

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianReviewApplyRequest,
    ObsidianLibrarianReviewQueueRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianLibrarianReviewQueueItem,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class ObsidianLibrarianReviewQueueRequestSchema(StrictSchemaModel):
    """Request for librarian curation candidates."""

    scope_path: Annotated[
        str | None,
        described_field("Scope path for this Obsidian librarian review queue request."),
    ] = None
    project: Annotated[
        str | None,
        described_field("Project for this Obsidian librarian review queue request."),
    ] = None
    limit: Annotated[
        int,
        described_field(
            "Limit for this Obsidian librarian review queue request.", ge=1, le=200
        ),
    ] = 50

    def to_command(self) -> ObsidianLibrarianReviewQueueRequest:
        """Convert request into application command.

        Returns:
            Application review queue request.
        """
        return ObsidianLibrarianReviewQueueRequest(
            scope_path=self.scope_path,
            project=self.project,
            limit=self.limit,
        )


class ObsidianLibrarianReviewQueueItemResponse(StrictSchemaModel):
    """One librarian curation queue item."""

    id: Annotated[
        str,
        described_field(
            "Stable identifier for this Obsidian librarian review queue item response."
        ),
    ]
    path: Annotated[
        str,
        described_field("Path for this Obsidian librarian review queue item response."),
    ]
    alexandria_type: Annotated[
        AlexandriaNoteType,
        described_field(
            "Alexandria type for this Obsidian librarian review queue item response."
        ),
    ]
    title: Annotated[
        str,
        described_field(
            "Title for this Obsidian librarian review queue item response."
        ),
    ]
    status: Annotated[
        str,
        described_field(
            "Status for this Obsidian librarian review queue item response."
        ),
    ]
    tags: Annotated[
        list[str],
        described_field("Tags for this Obsidian librarian review queue item response."),
    ]
    project: Annotated[
        str | None,
        described_field(
            "Project for this Obsidian librarian review queue item response."
        ),
    ]
    reason: Annotated[
        str,
        described_field(
            "Reason for this Obsidian librarian review queue item response."
        ),
    ]
    recommended_action: Annotated[
        str,
        described_field(
            "Recommended action for this Obsidian librarian review queue item response."
        ),
    ]
    suggested_destination_path: Annotated[
        str | None,
        described_field(
            "Suggested destination path for this Obsidian librarian review queue item response."
        ),
    ]
    priority: Annotated[
        int,
        described_field(
            "Priority for this Obsidian librarian review queue item response."
        ),
    ]
    confidence: Annotated[
        float,
        described_field(
            "Confidence for this Obsidian librarian review queue item response."
        ),
    ]
    requires_human_review: Annotated[
        bool,
        described_field(
            "Requires human review for this Obsidian librarian review queue item response."
        ),
    ]
    verification_query: Annotated[
        str | None,
        described_field(
            "Verification query for this Obsidian librarian review queue item response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        item: ObsidianLibrarianReviewQueueItem,
    ) -> ObsidianLibrarianReviewQueueItemResponse:
        """Create response from curation queue item.

        Args:
            item: Queue item entity.

        Returns:
            Queue item response.
        """
        return cls(
            id=item.note_id,
            path=item.relative_path,
            alexandria_type=item.alexandria_type,
            title=item.title,
            status=item.status,
            tags=list(item.tags),
            project=item.project,
            reason=item.reason,
            recommended_action=item.recommended_action,
            suggested_destination_path=item.suggested_destination_path,
            priority=item.priority,
            confidence=item.confidence,
            requires_human_review=item.requires_human_review,
            verification_query=item.verification_query,
        )


class ObsidianLibrarianReviewQueueResponse(StrictSchemaModel):
    """Librarian curation queue response."""

    items: Annotated[
        list[ObsidianLibrarianReviewQueueItemResponse],
        described_field("Items for this Obsidian librarian review queue response."),
    ]
    total: Annotated[
        int, described_field("Total for this Obsidian librarian review queue response.")
    ]


class ObsidianLibrarianReviewApplyRequestSchema(StrictSchemaModel):
    """Request to safely apply librarian review queue moves."""

    scope_path: Annotated[
        str | None,
        described_field("Scope path for this Obsidian librarian review apply request."),
    ] = None
    project: Annotated[
        str | None,
        described_field("Project for this Obsidian librarian review apply request."),
    ] = None
    limit: Annotated[
        int,
        described_field(
            "Limit for this Obsidian librarian review apply request.", ge=1, le=200
        ),
    ] = 50
    report_path: Annotated[
        str | None,
        described_field(
            "Report path for this Obsidian librarian review apply request."
        ),
    ] = None
    reindex: Annotated[
        bool,
        described_field("Reindex for this Obsidian librarian review apply request."),
    ] = True
    verification_query: Annotated[
        str | None,
        described_field(
            "Verification query for this Obsidian librarian review apply request."
        ),
    ] = None

    def to_command(self) -> ObsidianLibrarianReviewApplyRequest:
        """Convert request into application command.

        Returns:
            Application review apply request.
        """
        return ObsidianLibrarianReviewApplyRequest(
            scope_path=self.scope_path,
            project=self.project,
            limit=self.limit,
            report_path=self.report_path,
            reindex=self.reindex,
            verification_query=self.verification_query,
        )
