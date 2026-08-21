"""Policy validation for untrusted model-assisted memory relation proposals."""

from __future__ import annotations

from app.memory.application.reconciliation.conflicts.memory_temporal_policy import (
    intervals_overlap,
    is_temporally_newer,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemoryRecallCandidate,
    MemoryRelationDecision,
)
from app.memory.domain.entities.memory_relation_proposal import (
    MemoryRelationModelProposal,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryDecisionSource,
    MemoryRelationType,
)
from app.shared.types.types_convert_utils import now_utc

MODEL_POLICY_VERSION = "memory-reconciliation-v2-model-policy"
_MIN_MODEL_CONFIDENCE = 0.65


def model_proposal_decision(
    base: MemoryRelationDecision,
    proposal: MemoryRelationModelProposal,
    candidate: MemoryCandidate,
    existing: MemoryRecallCandidate,
) -> MemoryRelationDecision:
    """Adopt only a model proposal that passes deterministic safety policy.

    Args:
        base: Base.
        proposal: Proposal.
        candidate: Candidate.
        existing: Existing.

    Returns:
        MemoryRelationDecision: Operation result.
    """
    if base.relation is not MemoryRelationType.UNKNOWN:
        return base
    if proposal.relation is MemoryRelationType.UNKNOWN:
        return base
    if proposal.confidence < _MIN_MODEL_CONFIDENCE:
        return base
    if not _proposal_is_supported(
        proposal=proposal,
        base=base,
        candidate=candidate,
        existing=existing,
    ):
        return base
    return MemoryRelationDecision(
        candidate_id=base.candidate_id,
        existing_context_id=base.existing_context_id,
        relation=proposal.relation,
        confidence=proposal.confidence,
        reason=f"Model proposal accepted by policy: {proposal.reason}",
        evidence_refs=base.evidence_refs,
        claim_matches=base.claim_matches,
        scores=base.scores,
        decision_source=MemoryDecisionSource.LLM,
        policy_version=MODEL_POLICY_VERSION,
        created_at=now_utc(),
    )


def _proposal_is_supported(
    proposal: MemoryRelationModelProposal,
    base: MemoryRelationDecision,
    candidate: MemoryCandidate,
    existing: MemoryRecallCandidate,
) -> bool:
    relation = proposal.relation
    scores = base.scores
    if relation is MemoryRelationType.UNRELATED:
        return proposal.confidence >= 0.85 and scores.semantic_similarity < 0.5
    if scores.scope_compatibility == 0.0:
        return False
    if relation is MemoryRelationType.DUPLICATE:
        return max(scores.semantic_similarity, scores.claim_overlap) >= 0.85
    if relation is MemoryRelationType.SUPPORTS:
        return scores.claim_overlap >= 0.65 and scores.polarity_conflict == 0.0
    if relation is MemoryRelationType.EXTENDS:
        return scores.claim_overlap >= 0.5 and scores.polarity_conflict == 0.0
    if relation is MemoryRelationType.CONTRADICTS:
        return scores.temporal_compatibility == 1.0 and scores.polarity_conflict == 1.0
    if relation is MemoryRelationType.SUPERSEDES:
        return not intervals_overlap(
            left_from=candidate.valid_from,
            left_to=candidate.valid_to,
            right_from=existing.valid_from,
            right_to=existing.valid_to,
        ) and is_temporally_newer(
            candidate_valid_from=candidate.valid_from,
            candidate_observed_at=candidate.observed_at,
            existing_valid_from=existing.valid_from,
            existing_observed_at=existing.observed_at,
        )
    return False
