"""Strict plan, review queue, and result response schemas for memory reconciliation."""

from __future__ import annotations

from typing import Annotated

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
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp


class CanonicalClaimQualifierResponse(StrictSchemaModel):
    """One normalized canonical claim qualifier."""

    name: Annotated[
        str, described_field("Name for this canonical claim qualifier response.")
    ]
    value: Annotated[
        str, described_field("Value for this canonical claim qualifier response.")
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
        str, described_field("Subject for this canonical claim response.")
    ]
    predicate: Annotated[
        str, described_field("Predicate for this canonical claim response.")
    ]
    object: Annotated[str, described_field("Object for this canonical claim response.")]
    qualifiers: Annotated[
        list[CanonicalClaimQualifierResponse],
        described_field("Qualifiers for this canonical claim response."),
    ]
    scope: Annotated[
        ContextScope, described_field("Scope for this canonical claim response.")
    ]
    project: Annotated[
        str | None, described_field("Project for this canonical claim response.")
    ]
    valid_from: Annotated[
        AwareTimestamp | None,
        described_field("Valid from for this canonical claim response."),
    ]
    valid_to: Annotated[
        AwareTimestamp | None,
        described_field("Valid to for this canonical claim response."),
    ]
    polarity: Annotated[
        MemoryClaimPolarity,
        described_field("Polarity for this canonical claim response."),
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
        str, described_field("Source type for this memory source reference response.")
    ]
    source_id: Annotated[
        str,
        described_field("Source identifier for this memory source reference response."),
    ]
    title: Annotated[
        str, described_field("Title for this memory source reference response.")
    ]
    detail_path: Annotated[
        str, described_field("Detail path for this memory source reference response.")
    ]
    source_hash: Annotated[
        str | None,
        described_field("Source hash for this memory source reference response."),
    ]
    observed_at: Annotated[
        AwareTimestamp | None,
        described_field("Observed at for this memory source reference response."),
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
        str, described_field("Candidate identifier for this memory candidate response.")
    ]
    title: Annotated[str, described_field("Title for this memory candidate response.")]
    body: Annotated[str, described_field("Body for this memory candidate response.")]
    canonical_claims: Annotated[
        list[CanonicalClaimResponse],
        described_field("Canonical claims for this memory candidate response."),
    ]
    scope: Annotated[
        ContextScope, described_field("Scope for this memory candidate response.")
    ]
    project: Annotated[
        str | None, described_field("Project for this memory candidate response.")
    ]
    tags: Annotated[
        list[str], described_field("Tags for this memory candidate response.")
    ]
    source_refs: Annotated[
        list[MemorySourceReferenceResponse],
        described_field("Source refs for this memory candidate response."),
    ]
    recorded_at: Annotated[
        AwareTimestamp,
        described_field("Recorded at for this memory candidate response."),
    ]
    observed_at: Annotated[
        AwareTimestamp | None,
        described_field("Observed at for this memory candidate response."),
    ]
    valid_from: Annotated[
        AwareTimestamp | None,
        described_field("Valid from for this memory candidate response."),
    ]
    valid_to: Annotated[
        AwareTimestamp | None,
        described_field("Valid to for this memory candidate response."),
    ]
    requested_lifecycle: Annotated[
        str, described_field("Requested lifecycle for this memory candidate response.")
    ]
    content_hash: Annotated[
        str, described_field("Content hash for this memory candidate response.")
    ]
    workspace_id: Annotated[
        str | None,
        described_field("Workspace identifier for this memory candidate response."),
    ]
    agent_id: Annotated[
        str | None,
        described_field("Agent identifier for this memory candidate response."),
    ]
    user_id: Annotated[
        str | None,
        described_field("User identifier for this memory candidate response."),
    ]
    session_id: Annotated[
        str | None,
        described_field("Session identifier for this memory candidate response."),
    ]
    source_identity: Annotated[
        str | None,
        described_field("Source identity for this memory candidate response."),
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
        described_field(
            "Semantic similarity for this memory relation scores response."
        ),
    ]
    claim_overlap: Annotated[
        float,
        described_field("Claim overlap for this memory relation scores response."),
    ]
    scope_compatibility: Annotated[
        float,
        described_field(
            "Scope compatibility for this memory relation scores response."
        ),
    ]
    temporal_compatibility: Annotated[
        float,
        described_field(
            "Temporal compatibility for this memory relation scores response."
        ),
    ]
    source_independence: Annotated[
        float,
        described_field(
            "Source independence for this memory relation scores response."
        ),
    ]
    polarity_conflict: Annotated[
        float,
        described_field("Polarity conflict for this memory relation scores response."),
    ]
    specificity_change: Annotated[
        float,
        described_field("Specificity change for this memory relation scores response."),
    ]
    freshness: Annotated[
        float, described_field("Freshness for this memory relation scores response.")
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
        described_field(
            "Candidate identifier for this memory relation decision response."
        ),
    ]
    existing_context_id: Annotated[
        str,
        described_field(
            "Existing context identifier for this memory relation decision response."
        ),
    ]
    relation: Annotated[
        MemoryRelationType,
        described_field("Relation for this memory relation decision response."),
    ]
    confidence: Annotated[
        float, described_field("Confidence for this memory relation decision response.")
    ]
    reason: Annotated[
        str, described_field("Reason for this memory relation decision response.")
    ]
    evidence_refs: Annotated[
        list[MemorySourceReferenceResponse],
        described_field("Evidence refs for this memory relation decision response."),
    ]
    claim_matches: Annotated[
        list[str],
        described_field("Claim matches for this memory relation decision response."),
    ]
    scores: Annotated[
        MemoryRelationScoresResponse,
        described_field("Scores for this memory relation decision response."),
    ]
    decision_source: Annotated[
        MemoryDecisionSource,
        described_field("Decision source for this memory relation decision response."),
    ]
    policy_version: Annotated[
        str,
        described_field("Policy version for this memory relation decision response."),
    ]
    created_at: Annotated[
        AwareTimestamp,
        described_field(
            "Creation timestamp for this memory relation decision response."
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
