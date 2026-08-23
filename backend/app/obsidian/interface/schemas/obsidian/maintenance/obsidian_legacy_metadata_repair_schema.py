"""HTTP contracts for dry-run-first legacy metadata repair."""

from __future__ import annotations

from typing import Annotated

from app.obsidian.domain.entities.obsidian_legacy_metadata_repair import (
    ObsidianLegacyMetadataRepairCandidate,
    ObsidianLegacyMetadataRepairFinding,
    ObsidianLegacyMetadataRepairPlan,
    ObsidianLegacyMetadataRepairReport,
    ObsidianLegacyMetadataRepairResult,
)
from app.obsidian.interface.schemas.obsidian.obsidian_string_types import (
    ObsidianRepairPlanHash,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class ObsidianLegacyMetadataRepairFindingResponse(StrictSchemaModel):
    """One current and proposed legacy metadata value."""

    field_name: Annotated[
        str,
        described_field(
            "Field name for this Obsidian legacy metadata repair finding response."
        ),
    ]
    current_value: Annotated[
        str,
        described_field(
            "Current value for this Obsidian legacy metadata repair finding response."
        ),
    ]
    proposed_value: Annotated[
        list[str] | bool | None,
        described_field(
            "Proposed value for this Obsidian legacy metadata repair finding response."
        ),
    ]
    reason: Annotated[
        str,
        described_field(
            "Reason for this Obsidian legacy metadata repair finding response."
        ),
    ]
    is_repairable: Annotated[
        bool,
        described_field(
            "Is repairable for this Obsidian legacy metadata repair finding response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        finding: ObsidianLegacyMetadataRepairFinding,
    ) -> ObsidianLegacyMetadataRepairFindingResponse:
        """Build this schema from a domain entity.

        Args:
            finding: Legacy metadata finding to serialize into the response schema.

        Returns:
            Schema populated from the domain entity.
        """
        proposed = finding.proposed_value
        return cls(
            field_name=finding.field_name,
            current_value=finding.current_value,
            proposed_value=list(proposed) if isinstance(proposed, tuple) else proposed,
            reason=finding.reason,
            is_repairable=finding.is_repairable,
        )


class ObsidianLegacyMetadataRepairCandidateResponse(StrictSchemaModel):
    """One affected Markdown path bound to its current content hash."""

    note_path: Annotated[
        str,
        described_field(
            "Note path for this Obsidian legacy metadata repair candidate response."
        ),
    ]
    original_sha256: Annotated[
        str,
        described_field(
            "Original SHA-256 for this Obsidian legacy metadata repair candidate response."
        ),
    ]
    findings: Annotated[
        list[ObsidianLegacyMetadataRepairFindingResponse],
        described_field(
            "Findings for this Obsidian legacy metadata repair candidate response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        candidate: ObsidianLegacyMetadataRepairCandidate,
    ) -> ObsidianLegacyMetadataRepairCandidateResponse:
        """Build this schema from a domain entity.

        Args:
            candidate: Repair candidate to serialize into the response schema.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(
            note_path=candidate.note_path,
            original_sha256=candidate.original_sha256,
            findings=[
                ObsidianLegacyMetadataRepairFindingResponse.from_entity(finding)
                for finding in candidate.findings
            ],
        )


class ObsidianLegacyMetadataRepairPlanResponse(StrictSchemaModel):
    """Non-mutating scan report and hash lock for explicit apply."""

    plan_hash: Annotated[
        str,
        described_field(
            "Plan hash for this Obsidian legacy metadata repair plan response."
        ),
    ]
    dry_run: Annotated[
        bool,
        described_field(
            "Dry run for this Obsidian legacy metadata repair plan response."
        ),
    ]
    backup_required: Annotated[
        bool,
        described_field(
            "Backup required for this Obsidian legacy metadata repair plan response."
        ),
    ]
    scanned_documents: Annotated[
        int,
        described_field(
            "Scanned documents for this Obsidian legacy metadata repair plan response."
        ),
    ]
    affected_documents: Annotated[
        int,
        described_field(
            "Affected documents for this Obsidian legacy metadata repair plan response."
        ),
    ]
    repairable_fields: Annotated[
        int,
        described_field(
            "Repairable fields for this Obsidian legacy metadata repair plan response."
        ),
    ]
    manual_review_fields: Annotated[
        int,
        described_field(
            "Manual review fields for this Obsidian legacy metadata repair plan response."
        ),
    ]
    unrecoverable_redacted_urls: Annotated[
        int,
        described_field(
            "Unrecoverable redacted urls for this Obsidian legacy metadata repair plan response."
        ),
    ]
    candidates: Annotated[
        list[ObsidianLegacyMetadataRepairCandidateResponse],
        described_field(
            "Candidates for this Obsidian legacy metadata repair plan response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        plan: ObsidianLegacyMetadataRepairPlan,
    ) -> ObsidianLegacyMetadataRepairPlanResponse:
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
            scanned_documents=plan.scanned_documents,
            affected_documents=plan.affected_documents,
            repairable_fields=plan.repairable_fields,
            manual_review_fields=plan.manual_review_fields,
            unrecoverable_redacted_urls=plan.unrecoverable_redacted_urls,
            candidates=[
                ObsidianLegacyMetadataRepairCandidateResponse.from_entity(candidate)
                for candidate in plan.candidates
            ],
        )


class ObsidianLegacyMetadataRepairApplyRequest(StrictSchemaModel):
    """Explicit acceptance of the inspected plan hash."""

    expected_plan_hash: Annotated[
        ObsidianRepairPlanHash,
        described_field(
            "Expected plan hash for this Obsidian legacy metadata repair apply request."
        ),
    ]


class ObsidianLegacyMetadataRepairResultResponse(StrictSchemaModel):
    """Before/after hash evidence for one attempted document."""

    note_path: Annotated[
        str,
        described_field(
            "Note path for this Obsidian legacy metadata repair result response."
        ),
    ]
    before_sha256: Annotated[
        str,
        described_field(
            "Before SHA-256 for this Obsidian legacy metadata repair result response."
        ),
    ]
    after_sha256: Annotated[
        str,
        described_field(
            "After SHA-256 for this Obsidian legacy metadata repair result response."
        ),
    ]
    success: Annotated[
        bool,
        described_field(
            "Success for this Obsidian legacy metadata repair result response."
        ),
    ]
    failure_reason: Annotated[
        str | None,
        described_field(
            "Failure reason for this Obsidian legacy metadata repair result response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        result: ObsidianLegacyMetadataRepairResult,
    ) -> ObsidianLegacyMetadataRepairResultResponse:
        """Build this schema from a domain entity.

        Args:
            result: Operation result to serialize or persist.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(
            note_path=result.note_path,
            before_sha256=result.before_sha256,
            after_sha256=result.after_sha256,
            success=result.success,
            failure_reason=result.failure_reason,
        )


class ObsidianLegacyMetadataRepairReportResponse(StrictSchemaModel):
    """Applied repair evidence with verified backup location."""

    status: Annotated[
        str,
        described_field(
            "Status for this Obsidian legacy metadata repair report response."
        ),
    ]
    plan_hash: Annotated[
        str,
        described_field(
            "Plan hash for this Obsidian legacy metadata repair report response."
        ),
    ]
    backup_root: Annotated[
        str,
        described_field(
            "Backup root for this Obsidian legacy metadata repair report response."
        ),
    ]
    applied_count: Annotated[
        int,
        described_field(
            "Applied count for this Obsidian legacy metadata repair report response."
        ),
    ]
    failed_count: Annotated[
        int,
        described_field(
            "Failed count for this Obsidian legacy metadata repair report response."
        ),
    ]
    unrecoverable_redacted_urls: Annotated[
        int,
        described_field(
            "Unrecoverable redacted urls for this Obsidian legacy metadata repair report response."
        ),
    ]
    results: Annotated[
        list[ObsidianLegacyMetadataRepairResultResponse],
        described_field(
            "Results for this Obsidian legacy metadata repair report response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        report: ObsidianLegacyMetadataRepairReport,
    ) -> ObsidianLegacyMetadataRepairReportResponse:
        """Build this schema from a domain entity.

        Args:
            report: Report entity to serialize into the response schema.

        Returns:
            Schema populated from the domain entity.
        """
        return cls(
            status=report.status,
            plan_hash=report.plan_hash,
            backup_root=report.backup_root,
            applied_count=report.applied_count,
            failed_count=report.failed_count,
            unrecoverable_redacted_urls=report.unrecoverable_redacted_urls,
            results=[
                ObsidianLegacyMetadataRepairResultResponse.from_entity(result)
                for result in report.results
            ],
        )
