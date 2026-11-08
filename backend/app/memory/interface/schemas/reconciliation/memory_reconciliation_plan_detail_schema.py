"""Memory reconciliation plan detail schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.memory.domain.entities.memory_reconciliation import (
    MemoryEvolutionCandidateEvidence,
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
from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.schemas.datetime_schemas import AwareTimestamp


class MemoryReconciliationActionResponse(StrictSchemaModel):
    """One explicit action in an immutable reconciliation plan."""

    action_type: Annotated[
        MemoryReconciliationActionType,
        Field(
            description="Action type for this memory reconciliation action response."
        ),
    ]
    target_context_id: Annotated[
        str | None,
        Field(
            description="Target context identifier for this memory reconciliation action response."
        ),
    ]
    relation: Annotated[
        MemoryRelationType | None,
        Field(description="Relation for this memory reconciliation action response."),
    ]
    reason: Annotated[
        str, Field(description="Reason for this memory reconciliation action response.")
    ]


class MemoryEvolutionCandidatePairEvidenceResponse(StrictSchemaModel):
    """One bounded deterministic candidate pair emitted by Rust compute."""

    left_id: Annotated[str, Field(description="Left candidate item identifier.")]
    right_id: Annotated[str, Field(description="Right candidate item identifier.")]
    exact_content_hash: Annotated[
        bool,
        Field(description="Whether both items have the same non-empty content hash."),
    ]
    vector_similarity: Annotated[
        float | None, Field(description="Optional vector cosine similarity evidence.")
    ]
    temporal_overlap: Annotated[
        bool, Field(description="Whether the item validity intervals overlap.")
    ]
    graph_similarity: Annotated[
        float, Field(description="Graph-neighborhood Jaccard similarity evidence.")
    ]
    lineage: Annotated[
        str, Field(description="Deterministic lineage relation evidence.")
    ]
    candidate_score: Annotated[
        float, Field(description="Deterministic candidate evidence score.")
    ]
    reasons: Annotated[
        list[str],
        Field(description="Bounded deterministic reasons for the candidate pair."),
    ]


class MemoryEvolutionCandidateMetricsResponse(StrictSchemaModel):
    """Bounded-work counters from Rust reconciliation candidate discovery."""

    input_items: Annotated[
        int, Field(description="Candidate compute input items.", ge=0)
    ]
    comparison_pairs: Annotated[
        int,
        Field(description="Candidate pairs compared by deterministic compute.", ge=0),
    ]
    qualifying_pairs: Annotated[
        int, Field(description="Pairs qualifying before per-item truncation.", ge=0)
    ]
    retained_pairs: Annotated[
        int, Field(description="Pairs retained after bounded top-k truncation.", ge=0)
    ]
    exact_duplicate_groups: Annotated[
        int, Field(description="Exact content-hash duplicate groups.", ge=0)
    ]


class MemoryEvolutionCandidateEvidenceResponse(StrictSchemaModel):
    """Operator-auditable Rust evidence that never assigns final memory semantics."""

    compute_authority: Annotated[
        str, Field(description="Deterministic candidate-compute authority identifier.")
    ]
    candidate_item_id: Annotated[
        str,
        Field(
            description="Source memory proposal identifier used by candidate compute."
        ),
    ]
    compared_context_ids: Annotated[
        list[str],
        Field(description="Stored Context identifiers supplied to candidate compute."),
    ]
    candidate_pairs: Annotated[
        list[MemoryEvolutionCandidatePairEvidenceResponse],
        Field(description="Source-related deterministic candidate evidence pairs."),
    ]
    metrics: Annotated[
        MemoryEvolutionCandidateMetricsResponse,
        Field(description="Bounded-work metrics for this candidate compute execution."),
    ]

    @classmethod
    def from_entity(
        cls, value: MemoryEvolutionCandidateEvidence
    ) -> MemoryEvolutionCandidateEvidenceResponse:
        """Map one internal proposal-evidence record to its bounded API contract.

        Args:
            value: Persisted deterministic candidate evidence.

        Returns:
            Strict response without Context bodies or embedding vectors.
        """
        metrics = value.metrics
        return cls(
            compute_authority=value.compute_authority,
            candidate_item_id=value.candidate_item_id,
            compared_context_ids=list(value.compared_context_ids),
            candidate_pairs=[
                MemoryEvolutionCandidatePairEvidenceResponse(
                    left_id=pair.left_id,
                    right_id=pair.right_id,
                    exact_content_hash=pair.exact_content_hash,
                    vector_similarity=pair.vector_similarity,
                    temporal_overlap=pair.temporal_overlap,
                    graph_similarity=pair.graph_similarity,
                    lineage=pair.lineage,
                    candidate_score=pair.candidate_score,
                    reasons=list(pair.reasons),
                )
                for pair in value.candidate_pairs
            ],
            metrics=MemoryEvolutionCandidateMetricsResponse(
                input_items=metrics.input_items,
                comparison_pairs=metrics.comparison_pairs,
                qualifying_pairs=metrics.qualifying_pairs,
                retained_pairs=metrics.retained_pairs,
                exact_duplicate_groups=metrics.exact_duplicate_groups,
            ),
        )


class MemoryReconciliationPlanResponse(StrictSchemaModel):
    """Complete non-mutating reconciliation preview plan."""

    plan_id: Annotated[
        str,
        Field(
            description="Plan identifier for this memory reconciliation plan response."
        ),
    ]
    candidate: Annotated[
        MemoryCandidateResponse,
        Field(description="Candidate for this memory reconciliation plan response."),
    ]
    decisions: Annotated[
        list[MemoryRelationDecisionResponse],
        Field(description="Decisions for this memory reconciliation plan response."),
    ]
    primary_decision: Annotated[
        MemoryRelationType,
        Field(
            description="Primary decision for this memory reconciliation plan response."
        ),
    ]
    actions: Annotated[
        list[MemoryReconciliationActionResponse],
        Field(description="Actions for this memory reconciliation plan response."),
    ]
    warnings: Annotated[
        list[str],
        Field(description="Warnings for this memory reconciliation plan response."),
    ]
    conflicting_context_ids: Annotated[
        list[str],
        Field(
            description="Conflicting context identifiers for this memory reconciliation plan response."
        ),
    ]
    requires_review: Annotated[
        bool,
        Field(
            description="Requires review for this memory reconciliation plan response."
        ),
    ]
    idempotency_key: Annotated[
        str,
        Field(
            description="Idempotency key for this memory reconciliation plan response."
        ),
    ]
    status: Annotated[
        MemoryReconciliationStatus,
        Field(description="Status for this memory reconciliation plan response."),
    ]
    candidate_evidence: Annotated[
        MemoryEvolutionCandidateEvidenceResponse | None,
        Field(
            description="Optional deterministic candidate evidence retained for audit."
        ),
    ]
    created_at: Annotated[
        AwareTimestamp,
        Field(
            description="Creation timestamp for this memory reconciliation plan response."
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
            candidate_evidence=(
                None
                if value.candidate_evidence is None
                else MemoryEvolutionCandidateEvidenceResponse.from_entity(
                    value.candidate_evidence
                )
            ),
            created_at=value.created_at,
        )


class MemoryReviewQueueResponse(StrictSchemaModel):
    """Durable review-required reconciliation plans."""

    items: Annotated[
        list[MemoryReconciliationPlanResponse],
        Field(description="Items for this memory review queue response."),
    ]
    total: Annotated[
        int, Field(description="Total for this memory review queue response.")
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
        Field(
            description="Reconciliation identifier for this memory reconciliation result response."
        ),
    ]
    plan_id: Annotated[
        str,
        Field(
            description="Plan identifier for this memory reconciliation result response."
        ),
    ]
    status: Annotated[
        MemoryReconciliationStatus,
        Field(description="Status for this memory reconciliation result response."),
    ]
    created_context_ids: Annotated[
        list[str],
        Field(
            description="Created context identifiers for this memory reconciliation result response."
        ),
    ]
    updated_context_ids: Annotated[
        list[str],
        Field(
            description="Updated context identifiers for this memory reconciliation result response."
        ),
    ]
    superseded_context_ids: Annotated[
        list[str],
        Field(
            description="Superseded context identifiers for this memory reconciliation result response."
        ),
    ]
    created_relation_ids: Annotated[
        list[str],
        Field(
            description="Created relation identifiers for this memory reconciliation result response."
        ),
    ]
    created_conflict_set_ids: Annotated[
        list[str],
        Field(
            description="Created conflict set identifiers for this memory reconciliation result response."
        ),
    ]
    merged_evidence: Annotated[
        list[MemorySourceReferenceResponse],
        Field(
            description="Merged evidence for this memory reconciliation result response."
        ),
    ]
    review_queue_item_ids: Annotated[
        list[str],
        Field(
            description="Review queue item identifiers for this memory reconciliation result response."
        ),
    ]
    warnings: Annotated[
        list[str],
        Field(description="Warnings for this memory reconciliation result response."),
    ]
    hard_delete_performed: Annotated[
        bool,
        Field(
            description="Hard delete performed for this memory reconciliation result response."
        ),
    ]
    failure_code: Annotated[
        MemoryReconciliationFailureCode | None,
        Field(
            description="Failure code for this memory reconciliation result response."
        ),
    ]
    reviewed_by: Annotated[
        str | None,
        Field(
            description="Memory Steward identity that approved review-required mutation."
        ),
    ]
    reviewed_at: Annotated[
        AwareTimestamp | None,
        Field(description="Timestamp when review approval was consumed for mutation."),
    ]
    completed_at: Annotated[
        AwareTimestamp | None,
        Field(
            description="Completed at for this memory reconciliation result response."
        ),
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
            reviewed_by=value.reviewed_by,
            reviewed_at=value.reviewed_at,
            completed_at=value.completed_at,
        )
