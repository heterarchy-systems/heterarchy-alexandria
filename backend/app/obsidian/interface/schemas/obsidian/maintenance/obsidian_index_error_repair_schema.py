"""HTTP contracts for backup-first Obsidian index-error repair."""

from __future__ import annotations

from typing import Annotated

from app.obsidian.domain.entities.obsidian_index_error_repair import (
    ObsidianIndexErrorRepairCandidate,
    ObsidianIndexErrorRepairPlan,
    ObsidianIndexErrorRepairReport,
    ObsidianIndexErrorRepairSkip,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexErrorCode
from app.obsidian.interface.schemas.obsidian.obsidian_string_types import (
    ObsidianRepairPlanHash,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class ObsidianIndexErrorRepairCandidateResponse(StrictSchemaModel):
    """One planned source-hash-bound frontmatter repair."""

    note_path: Annotated[
        str,
        described_field(
            "Note path for this Obsidian index error repair candidate response."
        ),
    ]
    error_code: Annotated[
        ObsidianIndexErrorCode,
        described_field(
            "Error code for this Obsidian index error repair candidate response."
        ),
    ]
    original_sha256: Annotated[
        str,
        described_field(
            "Original SHA-256 for this Obsidian index error repair candidate response."
        ),
    ]
    replacements: Annotated[
        dict[str, str],
        described_field(
            "Replacements for this Obsidian index error repair candidate response."
        ),
    ]
    reason: Annotated[
        str,
        described_field(
            "Reason for this Obsidian index error repair candidate response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        item: ObsidianIndexErrorRepairCandidate,
    ) -> ObsidianIndexErrorRepairCandidateResponse:
        """Build this schema from a domain entity.

        Args:
            item: Domain item to serialize into the response schema.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(
            note_path=item.note_path,
            error_code=item.error_code,
            original_sha256=item.original_sha256,
            replacements=dict(item.replacements),
            reason=item.reason,
        )


class ObsidianIndexErrorRepairSkipResponse(StrictSchemaModel):
    """One index error requiring manual review."""

    note_path: Annotated[
        str,
        described_field(
            "Note path for this Obsidian index error repair skip response."
        ),
    ]
    error_code: Annotated[
        ObsidianIndexErrorCode,
        described_field(
            "Error code for this Obsidian index error repair skip response."
        ),
    ]
    reason: Annotated[
        str,
        described_field("Reason for this Obsidian index error repair skip response."),
    ]

    @classmethod
    def from_entity(
        cls,
        item: ObsidianIndexErrorRepairSkip,
    ) -> ObsidianIndexErrorRepairSkipResponse:
        """Build this schema from a domain entity.

        Args:
            item: Domain item to serialize into the response schema.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(
            note_path=item.note_path,
            error_code=item.error_code,
            reason=item.reason,
        )


class ObsidianIndexErrorRepairPlanResponse(StrictSchemaModel):
    """Dry-run plan which must remain unchanged before apply."""

    plan_hash: Annotated[
        str,
        described_field(
            "Plan hash for this Obsidian index error repair plan response."
        ),
    ]
    dry_run: Annotated[
        bool,
        described_field("Dry run for this Obsidian index error repair plan response."),
    ]
    backup_required: Annotated[
        bool,
        described_field(
            "Backup required for this Obsidian index error repair plan response."
        ),
    ]
    candidates: Annotated[
        list[ObsidianIndexErrorRepairCandidateResponse],
        described_field(
            "Candidates for this Obsidian index error repair plan response."
        ),
    ]
    skipped: Annotated[
        list[ObsidianIndexErrorRepairSkipResponse],
        described_field("Skipped for this Obsidian index error repair plan response."),
    ]

    @classmethod
    def from_entity(
        cls,
        plan: ObsidianIndexErrorRepairPlan,
    ) -> ObsidianIndexErrorRepairPlanResponse:
        """Build this schema from a domain entity.

        Args:
            plan: Recovery or repair plan being verified or serialized.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(
            plan_hash=plan.plan_hash,
            dry_run=plan.dry_run,
            backup_required=plan.backup_required,
            candidates=[
                ObsidianIndexErrorRepairCandidateResponse.from_entity(item)
                for item in plan.candidates
            ],
            skipped=[
                ObsidianIndexErrorRepairSkipResponse.from_entity(item)
                for item in plan.skipped
            ],
        )


class ObsidianIndexErrorRepairApplyRequest(StrictSchemaModel):
    """Hash-lock required to apply the most recently inspected source state."""

    expected_plan_hash: Annotated[
        ObsidianRepairPlanHash,
        described_field(
            "Expected plan hash for this Obsidian index error repair apply request."
        ),
    ]


class ObsidianIndexErrorRepairReportResponse(StrictSchemaModel):
    """Evidence for one applied, backup-first repair."""

    status: Annotated[
        str,
        described_field("Status for this Obsidian index error repair report response."),
    ]
    plan_hash: Annotated[
        str,
        described_field(
            "Plan hash for this Obsidian index error repair report response."
        ),
    ]
    applied_count: Annotated[
        int,
        described_field(
            "Applied count for this Obsidian index error repair report response."
        ),
    ]
    backup_root: Annotated[
        str,
        described_field(
            "Backup root for this Obsidian index error repair report response."
        ),
    ]
    report_markdown_path: Annotated[
        str,
        described_field(
            "Report markdown path for this Obsidian index error repair report response."
        ),
    ]
    report_json_path: Annotated[
        str,
        described_field(
            "Report JSON path for this Obsidian index error repair report response."
        ),
    ]
    residual_error_notes: Annotated[
        int,
        described_field(
            "Residual error notes for this Obsidian index error repair report response."
        ),
    ]
    residual_error_paths: Annotated[
        list[str],
        described_field(
            "Residual error paths for this Obsidian index error repair report response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        report: ObsidianIndexErrorRepairReport,
    ) -> ObsidianIndexErrorRepairReportResponse:
        """Build this schema from a domain entity.

        Args:
            report: Report entity to serialize into the response schema.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(
            status=report.status,
            plan_hash=report.plan_hash,
            applied_count=report.applied_count,
            backup_root=report.backup_root,
            report_markdown_path=report.report_markdown_path,
            report_json_path=report.report_json_path,
            residual_error_notes=report.residual_error_notes,
            residual_error_paths=list(report.residual_error_paths),
        )
