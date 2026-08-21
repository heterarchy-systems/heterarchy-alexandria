"""Deterministic-first relation classification for durable memories."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from app.memory.application.reconciliation.candidates.memory_model_relation_policy import (
    model_proposal_decision,
)
from app.memory.application.reconciliation.conflicts.memory_temporal_policy import (
    intervals_overlap,
    is_temporally_newer,
)
from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    MemoryCandidate,
    MemoryRecallCandidate,
    MemoryRelationDecision,
    MemoryRelationScores,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryDecisionSource,
    MemoryRelationType,
)
from app.memory.domain.repositories.contexts.memory_relation_proposal_provider import (
    IMemoryRelationProposalProvider,
)
from app.shared.types.types_convert_utils import now_utc

POLICY_VERSION = "memory-reconciliation-v1"


@dataclass(frozen=True, slots=True, kw_only=True)
class _ClaimComparison:
    exact: bool
    same_proposition: bool
    same_subject_predicate: bool
    polarity_conflict: bool
    object_conflict: bool
    candidate_more_specific: bool
    overlap: float
    summary: str


class MemoryRelationClassifier:
    """Classify one candidate against one recalled Context using explicit policy."""

    def __init__(
        self,
        proposal_provider: IMemoryRelationProposalProvider | None = None,
    ) -> None:
        self._proposal_provider = proposal_provider

    async def classify_with_model(
        self,
        candidate: MemoryCandidate,
        existing: MemoryRecallCandidate,
    ) -> MemoryRelationDecision:
        """Use a model proposal only when deterministic/semantic policy is unknown.

        Args:
            candidate: Candidate.
            existing: Existing.

        Returns:
            MemoryRelationDecision: Operation result.
        """
        base = self.classify(candidate, existing)
        if (
            base.relation is not MemoryRelationType.UNKNOWN
            or self._proposal_provider is None
        ):
            return base
        proposal = await self._proposal_provider.propose(candidate, existing)
        if proposal is None:
            return base
        return model_proposal_decision(
            base=base,
            proposal=proposal,
            candidate=candidate,
            existing=existing,
        )

    def classify(
        self,
        candidate: MemoryCandidate,
        existing: MemoryRecallCandidate,
    ) -> MemoryRelationDecision:
        """Return an explainable deterministic or semantic relation decision.

        Args:
            candidate: Candidate.
            existing: Existing.

        Returns:
            MemoryRelationDecision: Operation result.
        """
        scope_compatibility = _scope_compatibility(candidate, existing)
        temporal_overlap = intervals_overlap(
            left_from=candidate.valid_from,
            left_to=candidate.valid_to,
            right_from=existing.valid_from,
            right_to=existing.valid_to,
        )
        comparisons = tuple(
            _compare_claims(candidate_claim, existing_claim)
            for candidate_claim in candidate.canonical_claims
            for existing_claim in existing.canonical_claims
        )
        best = max(comparisons, key=lambda item: item.overlap, default=None)
        semantic_similarity = SequenceMatcher(
            None,
            _normalized_text(candidate.body),
            _normalized_text(existing.body),
        ).ratio()
        source_independence = _source_independence(candidate, existing)
        freshness = (
            1.0
            if is_temporally_newer(
                candidate_valid_from=candidate.valid_from,
                candidate_observed_at=candidate.observed_at,
                existing_valid_from=existing.valid_from,
                existing_observed_at=existing.observed_at,
            )
            else 0.0
        )
        scores = MemoryRelationScores(
            semantic_similarity=semantic_similarity,
            claim_overlap=0.0 if best is None else best.overlap,
            scope_compatibility=scope_compatibility,
            temporal_compatibility=1.0 if temporal_overlap else 0.0,
            source_independence=source_independence,
            polarity_conflict=(
                1.0 if best is not None and best.polarity_conflict else 0.0
            ),
            specificity_change=(
                1.0 if best is not None and best.candidate_more_specific else 0.0
            ),
            freshness=freshness,
        )
        relation, confidence, reason, source = _select_relation(
            candidate=candidate,
            existing=existing,
            best=best,
            scores=scores,
            temporal_overlap=temporal_overlap,
        )
        return MemoryRelationDecision(
            candidate_id=candidate.candidate_id,
            existing_context_id=existing.context_id,
            relation=relation,
            confidence=confidence,
            reason=reason,
            evidence_refs=candidate.source_refs,
            claim_matches=() if best is None else (best.summary,),
            scores=scores,
            decision_source=source,
            policy_version=POLICY_VERSION,
            created_at=now_utc(),
        )


def _select_relation(
    candidate: MemoryCandidate,
    existing: MemoryRecallCandidate,
    best: _ClaimComparison | None,
    scores: MemoryRelationScores,
    temporal_overlap: bool,
) -> tuple[MemoryRelationType, float, str, MemoryDecisionSource]:
    if candidate.content_hash == existing.content_hash:
        return (
            MemoryRelationType.DUPLICATE,
            1.0,
            "Exact content hash match",
            MemoryDecisionSource.DETERMINISTIC,
        )
    if (
        candidate.source_identity is not None
        and candidate.source_identity == existing.source_identity
        and scores.semantic_similarity >= 0.98
    ):
        return (
            MemoryRelationType.DUPLICATE,
            0.99,
            "Same source identity with equivalent content",
            MemoryDecisionSource.DETERMINISTIC,
        )
    if scores.scope_compatibility == 0.0:
        return (
            MemoryRelationType.UNRELATED,
            0.98,
            "Project or scope identities are incompatible",
            MemoryDecisionSource.DETERMINISTIC,
        )
    if best is None:
        relation = (
            MemoryRelationType.UNRELATED
            if scores.semantic_similarity < 0.35
            else MemoryRelationType.UNKNOWN
        )
        return (
            relation,
            0.75 if relation is MemoryRelationType.UNRELATED else 0.4,
            "No comparable canonical claims were available",
            MemoryDecisionSource.SEMANTIC,
        )
    if best.exact:
        relation = (
            MemoryRelationType.SUPPORTS
            if scores.source_independence > 0.0
            else MemoryRelationType.DUPLICATE
        )
        reason = (
            "Independent evidence supports the same canonical claim"
            if relation is MemoryRelationType.SUPPORTS
            else "Canonical claim is identical"
        )
        return relation, 0.98, reason, MemoryDecisionSource.DETERMINISTIC
    if (
        best.same_subject_predicate
        and (best.polarity_conflict or best.object_conflict)
        and temporal_overlap
    ):
        return (
            MemoryRelationType.CONTRADICTS,
            0.96,
            "Claims conflict within overlapping validity intervals",
            MemoryDecisionSource.DETERMINISTIC,
        )
    if best.same_subject_predicate and scores.freshness == 1.0 and not temporal_overlap:
        return (
            MemoryRelationType.SUPERSEDES,
            0.95,
            "Candidate describes a newer non-overlapping state",
            MemoryDecisionSource.DETERMINISTIC,
        )
    if best.same_proposition and best.candidate_more_specific:
        return (
            MemoryRelationType.EXTENDS,
            0.9,
            "Candidate adds qualifiers to the existing proposition",
            MemoryDecisionSource.DETERMINISTIC,
        )
    if scores.claim_overlap >= 0.75 and scores.semantic_similarity >= 0.7:
        return (
            MemoryRelationType.EXTENDS,
            0.78,
            "Candidate substantially overlaps and adds new detail",
            MemoryDecisionSource.SEMANTIC,
        )
    if scores.claim_overlap < 0.25 and scores.semantic_similarity < 0.35:
        return (
            MemoryRelationType.UNRELATED,
            0.9,
            "Claims and content have low overlap",
            MemoryDecisionSource.SEMANTIC,
        )
    return (
        MemoryRelationType.UNKNOWN,
        0.45,
        "Available evidence does not support a safe relation decision",
        MemoryDecisionSource.SEMANTIC,
    )


def _compare_claims(
    candidate: CanonicalClaim, existing: CanonicalClaim
) -> _ClaimComparison:
    subject_equal = _normalized_text(candidate.subject) == _normalized_text(
        existing.subject
    )
    predicate_equal = _normalized_text(candidate.predicate) == _normalized_text(
        existing.predicate
    )
    object_equal = _normalized_text(candidate.object) == _normalized_text(
        existing.object
    )
    qualifier_pairs = {(item.name, item.value) for item in candidate.qualifiers}
    existing_qualifier_pairs = {(item.name, item.value) for item in existing.qualifiers}
    same_subject_predicate = subject_equal and predicate_equal
    same_proposition = same_subject_predicate and object_equal
    exact = (
        same_proposition
        and candidate.polarity is existing.polarity
        and qualifier_pairs == existing_qualifier_pairs
    )
    polarity_conflict = same_proposition and candidate.polarity is not existing.polarity
    object_conflict = same_subject_predicate and not object_equal
    candidate_more_specific = (
        same_proposition
        and qualifier_pairs > existing_qualifier_pairs
        and candidate.polarity is existing.polarity
    )
    matched_parts = sum((subject_equal, predicate_equal, object_equal))
    qualifier_union = qualifier_pairs | existing_qualifier_pairs
    qualifier_overlap = (
        1.0
        if not qualifier_union
        else len(qualifier_pairs & existing_qualifier_pairs) / len(qualifier_union)
    )
    overlap = (matched_parts / 3 * 0.8) + (qualifier_overlap * 0.2)
    return _ClaimComparison(
        exact=exact,
        same_proposition=same_proposition,
        same_subject_predicate=same_subject_predicate,
        polarity_conflict=polarity_conflict,
        object_conflict=object_conflict,
        candidate_more_specific=candidate_more_specific,
        overlap=overlap,
        summary=f"{candidate.subject}|{candidate.predicate}|{candidate.object}",
    )


def _scope_compatibility(
    candidate: MemoryCandidate,
    existing: MemoryRecallCandidate,
) -> float:
    if candidate.scope is not existing.scope:
        return 0.0
    identities = {
        "GLOBAL": (None, None),
        "PROJECT": (candidate.project, existing.project),
        "WORKSPACE": (candidate.workspace_id, existing.workspace_id),
        "AGENT": (candidate.agent_id, existing.agent_id),
        "USER": (candidate.user_id, existing.user_id),
        "SESSION": (candidate.session_id, existing.session_id),
    }
    candidate_identity, existing_identity = identities[candidate.scope.value]
    return 1.0 if candidate_identity == existing_identity else 0.0


def _source_independence(
    candidate: MemoryCandidate,
    existing: MemoryRecallCandidate,
) -> float:
    candidate_ids = {
        (item.source_type, item.source_id) for item in candidate.source_refs
    }
    existing_ids = {(item.source_type, item.source_id) for item in existing.source_refs}
    if not candidate_ids or not existing_ids:
        return 0.0
    return 1.0 if candidate_ids.isdisjoint(existing_ids) else 0.0


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())
