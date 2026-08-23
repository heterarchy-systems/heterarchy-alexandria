"""Tests-only retrieval-kernel contract double for Python application integration."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.repositories.contexts.context_retrieval_kernel_provider import (
    IContextRetrievalKernelProvider,
)

_HYBRID_CANDIDATE_MULTIPLIER = 6
_MAX_HYBRID_CANDIDATE_LIMIT = 50
_RECIPROCAL_RANK_FUSION_CONSTANT = 60
_VECTOR_RECIPROCAL_RANK_WEIGHT = 1.01
_FUSED_RETRIEVAL_REASON = (
    "Context ranked across lexical and semantic vector evidence "
    "using best-lane reciprocal-rank fusion."
)


@dataclass(slots=True)
class _FusionEvidence:
    representative: ContextSearchMatch
    representative_contribution: float
    fused_score: float
    first_seen: int
    fts_score: float | None = None
    vector_score: float | None = None


@dataclass(frozen=True, slots=True)
class TestContextRetrievalKernelProvider(IContextRetrievalKernelProvider):
    """Provide deterministic ranking semantics only inside Python application tests."""

    __test__ = False

    @property
    def authority(self) -> str:
        """Return the tests-only authority identifier.

        Returns:
            ``test`` so runtime provenance cannot confuse this double with Rust.
        """
        return "test"

    def hybrid_candidate_limit(self, limit: int) -> int:
        """Return the frozen test contract candidate bound.

        Args:
            limit: Requested final result count.

        Returns:
            Bounded per-lane candidate count.
        """
        return min(
            _MAX_HYBRID_CANDIDATE_LIMIT,
            max(limit, limit * _HYBRID_CANDIDATE_MULTIPLIER),
        )

    def merge(
        self,
        fts_matches: list[ContextSearchMatch],
        vector_matches: list[ContextSearchMatch],
        limit: int,
    ) -> list[ContextSearchMatch]:
        """Return the frozen integration-test Hybrid ranking contract.

        Args:
            fts_matches: Ordered lexical lane.
            vector_matches: Ordered vector lane.
            limit: Maximum returned matches.

        Returns:
            Deterministically fused Context matches.
        """
        evidence_by_context: dict[str, _FusionEvidence] = {}
        first_seen = 0
        for lane_name, lane_matches in (
            ("fts", fts_matches),
            ("vector", vector_matches),
        ):
            seen_context_ids: set[str] = set()
            for rank, match in enumerate(lane_matches, start=1):
                context_id = match.context.id
                if context_id in seen_context_ids:
                    continue
                seen_context_ids.add(context_id)
                contribution = 1.0 / (_RECIPROCAL_RANK_FUSION_CONSTANT + rank)
                if lane_name == "vector":
                    contribution *= _VECTOR_RECIPROCAL_RANK_WEIGHT
                evidence = evidence_by_context.get(context_id)
                if evidence is None:
                    evidence = _FusionEvidence(
                        representative=match,
                        representative_contribution=contribution,
                        fused_score=0.0,
                        first_seen=first_seen,
                    )
                    evidence_by_context[context_id] = evidence
                    first_seen += 1
                evidence.fused_score = max(evidence.fused_score, contribution)
                if contribution > evidence.representative_contribution:
                    evidence.representative = match
                    evidence.representative_contribution = contribution
                if lane_name == "fts":
                    evidence.fts_score = match.fts_score
                else:
                    evidence.vector_score = match.vector_score
        ranked = sorted(
            evidence_by_context.values(),
            key=lambda evidence: (-evidence.fused_score, evidence.first_seen),
        )[:limit]
        return [_fused_match(evidence) for evidence in ranked]

    def rank_best(
        self,
        matches: list[ContextSearchMatch],
        limit: int,
    ) -> list[ContextSearchMatch]:
        """Return the highest-scoring chunk per Context for integration tests.

        Args:
            matches: Candidate matches.
            limit: Maximum returned Context count.

        Returns:
            Best match per Context in score order.
        """
        best_by_context: dict[str, ContextSearchMatch] = {}
        for match in matches:
            existing = best_by_context.get(match.context.id)
            if existing is None or match.score > existing.score:
                best_by_context[match.context.id] = match
        return sorted(
            best_by_context.values(),
            key=lambda match: match.score,
            reverse=True,
        )[:limit]


def _fused_match(evidence: _FusionEvidence) -> ContextSearchMatch:
    representative = evidence.representative
    why_retrieved = representative.why_retrieved
    if evidence.fts_score is not None and evidence.vector_score is not None:
        why_retrieved = _FUSED_RETRIEVAL_REASON
    return ContextSearchMatch(
        context=representative.context,
        chunk=representative.chunk,
        score=evidence.fused_score,
        fts_score=evidence.fts_score,
        vector_score=evidence.vector_score,
        why_retrieved=why_retrieved,
    )


def create_test_context_retrieval_kernel_provider() -> IContextRetrievalKernelProvider:
    """Create the deterministic tests-only retrieval provider.

    Returns:
        Fresh tests-only retrieval-kernel provider instance.
    """
    return TestContextRetrievalKernelProvider()
