"""Context retrieval ranking helpers."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.domain.entities.context_read_models import ContextSearchMatch

HYBRID_CANDIDATE_MULTIPLIER = 6
MAX_HYBRID_CANDIDATE_LIMIT = 50
RECIPROCAL_RANK_FUSION_CONSTANT = 60
VECTOR_RECIPROCAL_RANK_WEIGHT = 1.01


@dataclass(slots=True)
class _ContextFusionEvidence:
    """Mutable accumulator required while combining ranked retrieval lanes."""

    representative: ContextSearchMatch
    representative_contribution: float
    fused_score: float
    first_seen: int
    fts_score: float | None = None
    vector_score: float | None = None


def hybrid_candidate_limit(limit: int) -> int:
    """Return the bounded candidate count gathered per Hybrid retrieval lane.

    Args:
        limit: Requested final result count.

    Returns:
        Over-fetched candidate count used before rank fusion.
    """
    return min(
        MAX_HYBRID_CANDIDATE_LIMIT,
        max(limit, limit * HYBRID_CANDIDATE_MULTIPLIER),
    )


def merge_hybrid_matches(
    fts_matches: list[ContextSearchMatch],
    vector_matches: list[ContextSearchMatch],
    limit: int,
) -> list[ContextSearchMatch]:
    """Merge FTS and vector matches using best-lane reciprocal-rank fusion.

    Args:
        fts_matches: Ranked FTS matches.
        vector_matches: Ranked vector matches.
        limit: Maximum returned matches.

    Returns:
        list[ContextSearchMatch]: Hybrid-ranked matches.
    """
    evidence_by_context: dict[str, _ContextFusionEvidence] = {}
    first_seen = 0
    for source_name, source_matches in (
        ("fts", fts_matches),
        ("vector", vector_matches),
    ):
        seen_context_ids: set[str] = set()
        for rank, match in enumerate(source_matches, start=1):
            context_id = match.context.id
            if context_id in seen_context_ids:
                continue
            seen_context_ids.add(context_id)
            contribution = 1.0 / (RECIPROCAL_RANK_FUSION_CONSTANT + rank)
            if source_name == "vector":
                contribution *= VECTOR_RECIPROCAL_RANK_WEIGHT
            evidence = evidence_by_context.get(context_id)
            if evidence is None:
                evidence = _ContextFusionEvidence(
                    representative=match,
                    representative_contribution=contribution,
                    fused_score=0.0,
                    first_seen=first_seen,
                )
                evidence_by_context[context_id] = evidence
                first_seen += 1
            # FTS and vector search the same canonical content, so summing both
            # reciprocal-rank contributions can double-count correlated noise.
            evidence.fused_score = max(evidence.fused_score, contribution)
            if contribution > evidence.representative_contribution:
                evidence.representative = match
                evidence.representative_contribution = contribution
            if source_name == "fts":
                evidence.fts_score = match.fts_score
            else:
                evidence.vector_score = match.vector_score

    ranked_evidence = sorted(
        evidence_by_context.values(),
        key=lambda evidence: (-evidence.fused_score, evidence.first_seen),
    )
    return [_fused_context_match(evidence) for evidence in ranked_evidence[:limit]]


def _fused_context_match(evidence: _ContextFusionEvidence) -> ContextSearchMatch:
    representative = evidence.representative
    has_fts = evidence.fts_score is not None
    has_vector = evidence.vector_score is not None
    why_retrieved = representative.why_retrieved
    if has_fts and has_vector:
        why_retrieved = (
            "Context ranked across lexical and semantic vector evidence "
            "using best-lane reciprocal-rank fusion."
        )
    return ContextSearchMatch(
        context=representative.context,
        chunk=representative.chunk,
        score=evidence.fused_score,
        fts_score=evidence.fts_score,
        vector_score=evidence.vector_score,
        why_retrieved=why_retrieved,
    )


def rank_best_matches_per_context(
    matches: list[ContextSearchMatch],
    limit: int,
) -> list[ContextSearchMatch]:
    """Rank matches while keeping only the best chunk per context.

    Args:
        matches: Candidate matches from one or more retrieval sources.
        limit: Maximum returned contexts.

    Returns:
        Highest-scoring match per context, sorted by score.
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
