"""HTTP schema for Obsidian librarian workflow job status."""

from __future__ import annotations

from typing import Annotated

from app.obsidian.domain.entities.obsidian_note import (
    ObsidianLibrarianJob,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianLibrarianJobStatus,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp


class ObsidianLibrarianJobResponse(StrictSchemaModel):
    """Status response for one Obsidian librarian execution job."""

    job_id: Annotated[
        str, described_field("Job identifier for this Obsidian librarian job response.")
    ]
    status: Annotated[
        ObsidianLibrarianJobStatus,
        described_field("Status for this Obsidian librarian job response."),
    ]
    operation: Annotated[
        str, described_field("Operation for this Obsidian librarian job response.")
    ]
    result_available: Annotated[
        bool,
        described_field("Result available for this Obsidian librarian job response."),
    ]
    error_message: Annotated[
        str | None,
        described_field("Error message for this Obsidian librarian job response."),
    ]
    created_at: Annotated[
        AwareTimestamp,
        described_field("Creation timestamp for this Obsidian librarian job response."),
    ]
    updated_at: Annotated[
        AwareTimestamp,
        described_field(
            "Last-update timestamp for this Obsidian librarian job response."
        ),
    ]
    report_markdown_path: Annotated[
        str | None,
        described_field(
            "Report markdown path for this Obsidian librarian job response."
        ),
    ]
    report_json_path: Annotated[
        str | None,
        described_field("Report JSON path for this Obsidian librarian job response."),
    ]

    @classmethod
    def from_entity(cls, job: ObsidianLibrarianJob) -> ObsidianLibrarianJobResponse:
        """Create response from job snapshot.

        Args:
            job: Librarian job snapshot.

        Returns:
            Librarian job response.
        """
        report = job.report
        return cls(
            job_id=job.job_id,
            status=job.status,
            operation=job.operation,
            result_available=report is not None,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
            report_markdown_path=None
            if report is None
            else report.report_markdown_path,
            report_json_path=None if report is None else report.report_json_path,
        )
