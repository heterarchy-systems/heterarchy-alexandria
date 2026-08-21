"""Strict HTTP response schemas for existing-memory reconciliation."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.entities.memory_existing_reconciliation import (
    ExistingMemoryAssessment,
    ExistingMemoryReconciliationReport,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryRelationType
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class ExistingMemoryAssessmentResponse(StrictSchemaModel):
    """One existing Context assessment exposed at the HTTP boundary."""

    context_id: Annotated[
        str,
        described_field(
            "Context identifier for this existing memory assessment response."
        ),
    ]
    temporal_overlay_present: Annotated[
        bool,
        described_field(
            "Temporal overlay present for this existing memory assessment response."
        ),
    ]
    temporal_backfill_required: Annotated[
        bool,
        described_field(
            "Temporal backfill required for this existing memory assessment response."
        ),
    ]
    canonical_claim_count: Annotated[
        int,
        described_field(
            "Canonical claim count for this existing memory assessment response."
        ),
    ]
    primary_relation: Annotated[
        MemoryRelationType | None,
        described_field(
            "Primary relation for this existing memory assessment response."
        ),
    ]
    related_context_ids: Annotated[
        list[str],
        described_field(
            "Related context identifiers for this existing memory assessment response."
        ),
    ]
    plan_id: Annotated[
        str | None,
        described_field(
            "Plan identifier for this existing memory assessment response."
        ),
    ]
    plan_persisted: Annotated[
        bool,
        described_field("Plan persisted for this existing memory assessment response."),
    ]
    requires_review: Annotated[
        bool,
        described_field(
            "Requires review for this existing memory assessment response."
        ),
    ]
    warnings: Annotated[
        list[str],
        described_field("Warnings for this existing memory assessment response."),
    ]

    @classmethod
    def from_entity(
        cls,
        value: ExistingMemoryAssessment,
    ) -> ExistingMemoryAssessmentResponse:
        """Map one internal assessment into a strict response model.

        Args:
            value: Value.

        Returns:
            ExistingMemoryAssessmentResponse: Operation result.
        """
        return cls(
            context_id=value.context_id,
            temporal_overlay_present=value.temporal_overlay_present,
            temporal_backfill_required=value.temporal_backfill_required,
            canonical_claim_count=value.canonical_claim_count,
            primary_relation=value.primary_relation,
            related_context_ids=list(value.related_context_ids),
            plan_id=value.plan_id,
            plan_persisted=value.plan_persisted,
            requires_review=value.requires_review,
            warnings=list(value.warnings),
        )


class ExistingMemoryReconciliationResponse(StrictSchemaModel):
    """Dry-run or apply report for one bounded existing-memory scan."""

    dry_run: Annotated[
        bool,
        described_field("Dry run for this existing memory reconciliation response."),
    ]
    scanned: Annotated[
        int,
        described_field("Scanned for this existing memory reconciliation response."),
    ]
    total_available: Annotated[
        int,
        described_field(
            "Total available for this existing memory reconciliation response."
        ),
    ]
    temporal_backfill_candidates: Annotated[
        int,
        described_field(
            "Temporal backfill candidates for this existing memory reconciliation response."
        ),
    ]
    temporal_states_written: Annotated[
        int,
        described_field(
            "Temporal states written for this existing memory reconciliation response."
        ),
    ]
    plans_generated: Annotated[
        int,
        described_field(
            "Plans generated for this existing memory reconciliation response."
        ),
    ]
    plans_persisted: Annotated[
        int,
        described_field(
            "Plans persisted for this existing memory reconciliation response."
        ),
    ]
    contexts_missing_claims: Annotated[
        int,
        described_field(
            "Contexts missing claims for this existing memory reconciliation response."
        ),
    ]
    review_required: Annotated[
        int,
        described_field(
            "Review required for this existing memory reconciliation response."
        ),
    ]
    assessments: Annotated[
        list[ExistingMemoryAssessmentResponse],
        described_field(
            "Assessments for this existing memory reconciliation response."
        ),
    ]
    warnings: Annotated[
        list[str],
        described_field("Warnings for this existing memory reconciliation response."),
    ]
    hard_delete_performed: Annotated[
        bool,
        described_field(
            "Hard delete performed for this existing memory reconciliation response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        value: ExistingMemoryReconciliationReport,
    ) -> ExistingMemoryReconciliationResponse:
        """Map one internal scan report into a strict response model.

        Args:
            value: Value.

        Returns:
            ExistingMemoryReconciliationResponse: Operation result.
        """
        return cls(
            dry_run=value.dry_run,
            scanned=value.scanned,
            total_available=value.total_available,
            temporal_backfill_candidates=value.temporal_backfill_candidates,
            temporal_states_written=value.temporal_states_written,
            plans_generated=value.plans_generated,
            plans_persisted=value.plans_persisted,
            contexts_missing_claims=value.contexts_missing_claims,
            review_required=value.review_required,
            assessments=[
                ExistingMemoryAssessmentResponse.from_entity(item)
                for item in value.assessments
            ],
            warnings=list(value.warnings),
            hard_delete_performed=value.hard_delete_performed,
        )
