"""Strict plan, review queue, and result response schemas for memory reconciliation."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    CanonicalClaimQualifier,
    MemoryCandidate,
    MemoryRelationDecision,
    MemoryRelationScores,
    MemorySourceReference,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryClaimPolarity,
    MemoryDecisionSource,
    MemoryRelationType,
)
from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.schemas.datetime_schemas import AwareTimestamp


class CanonicalClaimQualifierResponse(StrictSchemaModel):
    """One normalized canonical claim qualifier."""

    name: Annotated[
        str, Field(description="Name for this canonical claim qualifier response.")
    ]
    value: Annotated[
        str, Field(description="Value for this canonical claim qualifier response.")
    ]

    @classmethod
    def from_entity(
        cls,
        value: CanonicalClaimQualifier,
    ) -> CanonicalClaimQualifierResponse:
        """Map one internal claim qualifier into a strict response.

        Args:
            value: Internal canonical claim qualifier.

        Returns:
            Explicitly mapped qualifier response.
        """
        return cls(name=value.name, value=value.value)


class CanonicalClaimResponse(StrictSchemaModel):
    """One normalized canonical proposition."""

    subject: Annotated[
        str, Field(description="Subject for this canonical claim response.")
    ]
    predicate: Annotated[
        str, Field(description="Predicate for this canonical claim response.")
    ]
    object: Annotated[
        str, Field(description="Object for this canonical claim response.")
    ]
    qualifiers: Annotated[
        list[CanonicalClaimQualifierResponse],
        Field(description="Qualifiers for this canonical claim response."),
    ]
    scope: Annotated[
        ContextScope, Field(description="Scope for this canonical claim response.")
    ]
    project: Annotated[
        str | None, Field(description="Project for this canonical claim response.")
    ]
    valid_from: Annotated[
        AwareTimestamp | None,
        Field(description="Valid from for this canonical claim response."),
    ]
    valid_to: Annotated[
        AwareTimestamp | None,
        Field(description="Valid to for this canonical claim response."),
    ]
    polarity: Annotated[
        MemoryClaimPolarity,
        Field(description="Polarity for this canonical claim response."),
    ]

    @classmethod
    def from_entity(cls, value: CanonicalClaim) -> CanonicalClaimResponse:
        """Map one internal canonical claim into a strict response.

        Args:
            value: Internal canonical claim.

        Returns:
            Explicitly mapped canonical claim response.
        """
        return cls(
            subject=value.subject,
            predicate=value.predicate,
            object=value.object,
            qualifiers=[
                CanonicalClaimQualifierResponse.from_entity(qualifier)
                for qualifier in value.qualifiers
            ],
            scope=value.scope,
            project=value.project,
            valid_from=value.valid_from,
            valid_to=value.valid_to,
            polarity=value.polarity,
        )


class MemorySourceReferenceResponse(StrictSchemaModel):
    """One normalized evidence or provenance reference."""

    source_type: Annotated[
        str, Field(description="Source type for this memory source reference response.")
    ]
    source_id: Annotated[
        str,
        Field(
            description="Source identifier for this memory source reference response."
        ),
    ]
    title: Annotated[
        str, Field(description="Title for this memory source reference response.")
    ]
    detail_path: Annotated[
        str, Field(description="Detail path for this memory source reference response.")
    ]
    source_hash: Annotated[
        str | None,
        Field(description="Source hash for this memory source reference response."),
    ]
    observed_at: Annotated[
        AwareTimestamp | None,
        Field(description="Observed at for this memory source reference response."),
    ]

    @classmethod
    def from_entity(
        cls,
        value: MemorySourceReference,
    ) -> MemorySourceReferenceResponse:
        """Map one internal evidence reference into a strict response.

        Args:
            value: Internal source reference.

        Returns:
            Explicitly mapped source-reference response.
        """
        return cls(
            source_type=value.source_type,
            source_id=value.source_id,
            title=value.title,
            detail_path=value.detail_path,
            source_hash=value.source_hash,
            observed_at=value.observed_at,
        )


class MemoryCandidateResponse(StrictSchemaModel):
    """Normalized memory candidate included in a reconciliation plan."""

    candidate_id: Annotated[
        str,
        Field(description="Candidate identifier for this memory candidate response."),
    ]
    title: Annotated[
        str, Field(description="Title for this memory candidate response.")
    ]
    body: Annotated[str, Field(description="Body for this memory candidate response.")]
    canonical_claims: Annotated[
        list[CanonicalClaimResponse],
        Field(description="Canonical claims for this memory candidate response."),
    ]
    scope: Annotated[
        ContextScope, Field(description="Scope for this memory candidate response.")
    ]
    project: Annotated[
        str | None, Field(description="Project for this memory candidate response.")
    ]
    tags: Annotated[
        list[str], Field(description="Tags for this memory candidate response.")
    ]
    source_refs: Annotated[
        list[MemorySourceReferenceResponse],
        Field(description="Source refs for this memory candidate response."),
    ]
    recorded_at: Annotated[
        AwareTimestamp,
        Field(description="Recorded at for this memory candidate response."),
    ]
    observed_at: Annotated[
        AwareTimestamp | None,
        Field(description="Observed at for this memory candidate response."),
    ]
    valid_from: Annotated[
        AwareTimestamp | None,
        Field(description="Valid from for this memory candidate response."),
    ]
    valid_to: Annotated[
        AwareTimestamp | None,
        Field(description="Valid to for this memory candidate response."),
    ]
    requested_lifecycle: Annotated[
        str,
        Field(description="Requested lifecycle for this memory candidate response."),
    ]
    content_hash: Annotated[
        str, Field(description="Content hash for this memory candidate response.")
    ]
    workspace_id: Annotated[
        str | None,
        Field(description="Workspace identifier for this memory candidate response."),
    ]
    agent_id: Annotated[
        str | None,
        Field(description="Agent identifier for this memory candidate response."),
    ]
    user_id: Annotated[
        str | None,
        Field(description="User identifier for this memory candidate response."),
    ]
    session_id: Annotated[
        str | None,
        Field(description="Session identifier for this memory candidate response."),
    ]
    source_identity: Annotated[
        str | None,
        Field(description="Source identity for this memory candidate response."),
    ]

    @classmethod
    def from_entity(cls, value: MemoryCandidate) -> MemoryCandidateResponse:
        """Map one internal candidate into a strict response.

        Args:
            value: Internal normalized memory candidate.

        Returns:
            Explicitly mapped candidate response.
        """
        return cls(
            candidate_id=value.candidate_id,
            title=value.title,
            body=value.body,
            canonical_claims=[
                CanonicalClaimResponse.from_entity(claim)
                for claim in value.canonical_claims
            ],
            scope=value.scope,
            project=value.project,
            tags=list(value.tags),
            source_refs=[
                MemorySourceReferenceResponse.from_entity(reference)
                for reference in value.source_refs
            ],
            recorded_at=value.recorded_at,
            observed_at=value.observed_at,
            valid_from=value.valid_from,
            valid_to=value.valid_to,
            requested_lifecycle=value.requested_lifecycle,
            content_hash=value.content_hash,
            workspace_id=value.workspace_id,
            agent_id=value.agent_id,
            user_id=value.user_id,
            session_id=value.session_id,
            source_identity=value.source_identity,
        )


class MemoryRelationScoresResponse(StrictSchemaModel):
    """Independent scoring axes behind one relation decision."""

    semantic_similarity: Annotated[
        float,
        Field(
            description="Semantic similarity for this memory relation scores response."
        ),
    ]
    claim_overlap: Annotated[
        float,
        Field(description="Claim overlap for this memory relation scores response."),
    ]
    scope_compatibility: Annotated[
        float,
        Field(
            description="Scope compatibility for this memory relation scores response."
        ),
    ]
    temporal_compatibility: Annotated[
        float,
        Field(
            description="Temporal compatibility for this memory relation scores response."
        ),
    ]
    source_independence: Annotated[
        float,
        Field(
            description="Source independence for this memory relation scores response."
        ),
    ]
    polarity_conflict: Annotated[
        float,
        Field(
            description="Polarity conflict for this memory relation scores response."
        ),
    ]
    specificity_change: Annotated[
        float,
        Field(
            description="Specificity change for this memory relation scores response."
        ),
    ]
    freshness: Annotated[
        float, Field(description="Freshness for this memory relation scores response.")
    ]

    @classmethod
    def from_entity(
        cls,
        value: MemoryRelationScores,
    ) -> MemoryRelationScoresResponse:
        """Map internal relation scores into a strict response.

        Args:
            value: Internal relation scoring axes.

        Returns:
            Explicitly mapped relation-score response.
        """
        return cls(
            semantic_similarity=value.semantic_similarity,
            claim_overlap=value.claim_overlap,
            scope_compatibility=value.scope_compatibility,
            temporal_compatibility=value.temporal_compatibility,
            source_independence=value.source_independence,
            polarity_conflict=value.polarity_conflict,
            specificity_change=value.specificity_change,
            freshness=value.freshness,
        )


class MemoryRelationDecisionResponse(StrictSchemaModel):
    """Explainable relation decision against one existing Context."""

    candidate_id: Annotated[
        str,
        Field(
            description="Candidate identifier for this memory relation decision response."
        ),
    ]
    existing_context_id: Annotated[
        str,
        Field(
            description="Existing context identifier for this memory relation decision response."
        ),
    ]
    relation: Annotated[
        MemoryRelationType,
        Field(description="Relation for this memory relation decision response."),
    ]
    confidence: Annotated[
        float,
        Field(description="Confidence for this memory relation decision response."),
    ]
    reason: Annotated[
        str, Field(description="Reason for this memory relation decision response.")
    ]
    evidence_refs: Annotated[
        list[MemorySourceReferenceResponse],
        Field(description="Evidence refs for this memory relation decision response."),
    ]
    claim_matches: Annotated[
        list[str],
        Field(description="Claim matches for this memory relation decision response."),
    ]
    scores: Annotated[
        MemoryRelationScoresResponse,
        Field(description="Scores for this memory relation decision response."),
    ]
    decision_source: Annotated[
        MemoryDecisionSource,
        Field(
            description="Decision source for this memory relation decision response."
        ),
    ]
    policy_version: Annotated[
        str,
        Field(description="Policy version for this memory relation decision response."),
    ]
    created_at: Annotated[
        AwareTimestamp,
        Field(
            description="Creation timestamp for this memory relation decision response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        value: MemoryRelationDecision,
    ) -> MemoryRelationDecisionResponse:
        """Map one internal relation decision into a strict response.

        Args:
            value: Internal explainable relation decision.

        Returns:
            Explicitly mapped relation-decision response.
        """
        return cls(
            candidate_id=value.candidate_id,
            existing_context_id=value.existing_context_id,
            relation=value.relation,
            confidence=value.confidence,
            reason=value.reason,
            evidence_refs=[
                MemorySourceReferenceResponse.from_entity(reference)
                for reference in value.evidence_refs
            ],
            claim_matches=list(value.claim_matches),
            scores=MemoryRelationScoresResponse.from_entity(value.scores),
            decision_source=value.decision_source,
            policy_version=value.policy_version,
            created_at=value.created_at,
        )
