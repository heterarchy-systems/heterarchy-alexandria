"""Memory reconciliation plan detail schema contracts."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.entities.memory_reconciliation import (
    MemoryReconciliationPlan,
    MemoryReconciliationResult,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryReconciliationActionType,
    MemoryReconciliationFailureCode,
    MemoryReconciliationStatus,
    MemoryRelationType,
)
from app.memory.interface.schemas.reconciliation.memory_reconciliation_plan_response_schema import (
    MemoryCandidateResponse,
    MemoryRelationDecisionResponse,
    MemorySourceReferenceResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp


class MemoryReconciliationActionResponse(StrictSchemaModel):
    """One explicit action in an immutable reconciliation plan."""

    action_type: Annotated[
        MemoryReconciliationActionType,
        described_field("Action type for this memory reconciliation action response."),
    ]
    target_context_id: Annotated[
        str | None,
        described_field(
            "Target context identifier for this memory reconciliation action response."
        ),
    ]
    relation: Annotated[
        MemoryRelationType | None,
        described_field("Relation for this memory reconciliation action response."),
    ]
    reason: Annotated[
        str, described_field("Reason for this memory reconciliation action response.")
    ]


class MemoryReconciliationPlanResponse(StrictSchemaModel):
    """Complete non-mutating reconciliation preview plan."""

    plan_id: Annotated[
        str,
        described_field(
            "Plan identifier for this memory reconciliation plan response."
        ),
    ]
    candidate: Annotated[
        MemoryCandidateResponse,
        described_field("Candidate for this memory reconciliation plan response."),
    ]
    decisions: Annotated[
        list[MemoryRelationDecisionResponse],
        described_field("Decisions for this memory reconciliation plan response."),
    ]
    primary_decision: Annotated[
        MemoryRelationType,
        described_field(
            "Primary decision for this memory reconciliation plan response."
        ),
    ]
    actions: Annotated[
        list[MemoryReconciliationActionResponse],
        described_field("Actions for this memory reconciliation plan response."),
    ]
    warnings: Annotated[
        list[str],
        described_field("Warnings for this memory reconciliation plan response."),
    ]
    conflicting_context_ids: Annotated[
        list[str],
        described_field(
            "Conflicting context identifiers for this memory reconciliation plan response."
        ),
    ]
    requires_review: Annotated[
        bool,
        described_field(
            "Requires review for this memory reconciliation plan response."
        ),
    ]
    idempotency_key: Annotated[
        str,
        described_field(
            "Idempotency key for this memory reconciliation plan response."
        ),
    ]
    status: Annotated[
        MemoryReconciliationStatus,
        described_field("Status for this memory reconciliation plan response."),
    ]
    created_at: Annotated[
        AwareTimestamp,
        described_field(
            "Creation timestamp for this memory reconciliation plan response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        value: MemoryReconciliationPlan,
    ) -> MemoryReconciliationPlanResponse:
        """Map one internal reconciliation plan into a strict response.

        Args:
            value: Immutable internal reconciliation plan.

        Returns:
            Explicitly mapped plan response.
        """
        return cls(
            plan_id=value.plan_id,
            candidate=MemoryCandidateResponse.from_entity(value.candidate),
            decisions=[
                MemoryRelationDecisionResponse.from_entity(decision)
                for decision in value.decisions
            ],
            primary_decision=value.primary_decision,
            actions=[
                MemoryReconciliationActionResponse(
                    action_type=action.action_type,
                    target_context_id=action.target_context_id,
                    relation=action.relation,
                    reason=action.reason,
                )
                for action in value.actions
            ],
            warnings=list(value.warnings),
            conflicting_context_ids=list(value.conflicting_context_ids),
            requires_review=value.requires_review,
            idempotency_key=value.idempotency_key,
            status=value.status,
            created_at=value.created_at,
        )


class MemoryReviewQueueResponse(StrictSchemaModel):
    """Durable review-required reconciliation plans."""

    items: Annotated[
        list[MemoryReconciliationPlanResponse],
        described_field("Items for this memory review queue response."),
    ]
    total: Annotated[
        int, described_field("Total for this memory review queue response.")
    ]

    @classmethod
    def from_entities(
        cls,
        values: list[MemoryReconciliationPlan],
    ) -> MemoryReviewQueueResponse:
        """Map persisted review-required plans into one queue response.

        Args:
            values: Values.

        Returns:
            MemoryReviewQueueResponse: Operation result.
        """
        items = [
            MemoryReconciliationPlanResponse.from_entity(value) for value in values
        ]
        return cls(items=items, total=len(items))


class MemoryReconciliationResultResponse(StrictSchemaModel):
    """Auditable result of applying one reconciliation plan."""

    reconciliation_id: Annotated[
        str,
        described_field(
            "Reconciliation identifier for this memory reconciliation result response."
        ),
    ]
    plan_id: Annotated[
        str,
        described_field(
            "Plan identifier for this memory reconciliation result response."
        ),
    ]
    status: Annotated[
        MemoryReconciliationStatus,
        described_field("Status for this memory reconciliation result response."),
    ]
    created_context_ids: Annotated[
        list[str],
        described_field(
            "Created context identifiers for this memory reconciliation result response."
        ),
    ]
    updated_context_ids: Annotated[
        list[str],
        described_field(
            "Updated context identifiers for this memory reconciliation result response."
        ),
    ]
    superseded_context_ids: Annotated[
        list[str],
        described_field(
            "Superseded context identifiers for this memory reconciliation result response."
        ),
    ]
    created_relation_ids: Annotated[
        list[str],
        described_field(
            "Created relation identifiers for this memory reconciliation result response."
        ),
    ]
    created_conflict_set_ids: Annotated[
        list[str],
        described_field(
            "Created conflict set identifiers for this memory reconciliation result response."
        ),
    ]
    merged_evidence: Annotated[
        list[MemorySourceReferenceResponse],
        described_field(
            "Merged evidence for this memory reconciliation result response."
        ),
    ]
    review_queue_item_ids: Annotated[
        list[str],
        described_field(
            "Review queue item identifiers for this memory reconciliation result response."
        ),
    ]
    warnings: Annotated[
        list[str],
        described_field("Warnings for this memory reconciliation result response."),
    ]
    hard_delete_performed: Annotated[
        bool,
        described_field(
            "Hard delete performed for this memory reconciliation result response."
        ),
    ]
    failure_code: Annotated[
        MemoryReconciliationFailureCode | None,
        described_field("Failure code for this memory reconciliation result response."),
    ]
    completed_at: Annotated[
        AwareTimestamp | None,
        described_field("Completed at for this memory reconciliation result response."),
    ]

    @classmethod
    def from_entity(
        cls,
        value: MemoryReconciliationResult,
    ) -> MemoryReconciliationResultResponse:
        """Map one internal reconciliation result into a strict response.

        Args:
            value: Immutable internal reconciliation result.

        Returns:
            Explicitly mapped reconciliation result response.
        """
        return cls(
            reconciliation_id=value.reconciliation_id,
            plan_id=value.plan_id,
            status=value.status,
            created_context_ids=list(value.created_context_ids),
            updated_context_ids=list(value.updated_context_ids),
            superseded_context_ids=list(value.superseded_context_ids),
            created_relation_ids=list(value.created_relation_ids),
            created_conflict_set_ids=list(value.created_conflict_set_ids),
            merged_evidence=[
                MemorySourceReferenceResponse.from_entity(reference)
                for reference in value.merged_evidence
            ],
            review_queue_item_ids=list(value.review_queue_item_ids),
            warnings=list(value.warnings),
            hard_delete_performed=value.hard_delete_performed,
            failure_code=value.failure_code,
            completed_at=value.completed_at,
        )
