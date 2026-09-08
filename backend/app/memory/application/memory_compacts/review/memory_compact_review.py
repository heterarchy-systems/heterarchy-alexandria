"""Deterministic Memory Compact quality review rubric."""

from __future__ import annotations

from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactReviewResult,
    MemoryCompactRubricScore,
    MemoryCompactSourceObservation,
)
from app.memory.application.memory_compacts.review.memory_compact_review_evidence import (
    _contradictions,
    _missing_ref_reasons,
    _recommended_actions,
    _stale_reasons,
)
from app.memory.application.memory_compacts.review.memory_compact_review_scoring import (
    _REQUIRED_TWO_SCORE_CODES,
    _RUBRIC,
    _markdown_sections,
    _score_rubric_item,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
)

__all__ = (
    "MemoryCompactReviewResult",
    "MemoryCompactRubricScore",
    "MemoryCompactSourceObservation",
    "review_memory_compact",
)


def review_memory_compact(
    compact: MemoryCompact,
    source_observations: tuple[MemoryCompactSourceObservation, ...] = (),
) -> MemoryCompactReviewResult:
    """Review a compact using the required quality rubric.

    Args:
        compact: Compact under review.
        source_observations: Optional current source-hash evidence.

    Returns:
        Structured review verdict, rubric scores, and recommended actions.
    """
    sections = _markdown_sections(compact.markdown_body)
    missing_refs = _missing_ref_reasons(compact.source_refs)
    stale_reasons = _stale_reasons(compact.source_refs, source_observations)
    contradictions = _contradictions(compact.markdown_body)
    scores = tuple(
        _score_rubric_item(
            spec=spec,
            compact=compact,
            sections=sections,
            missing_refs=missing_refs,
            stale_reasons=stale_reasons,
            contradictions=contradictions,
        )
        for spec in _RUBRIC
    )
    total_score = sum(score.score for score in scores)
    score_by_code = {score.code: score.score for score in scores}
    blocking_reasons = bool(missing_refs or stale_reasons or contradictions)
    required_zero = any(score.required and score.score == 0 for score in scores)
    required_two_missing = any(
        score_by_code[code] < 2 for code in _REQUIRED_TWO_SCORE_CODES
    )
    if blocking_reasons:
        verdict = MemoryCompactReviewVerdict.BLOCKED
    elif required_zero or required_two_missing or total_score < 17:
        verdict = MemoryCompactReviewVerdict.NEEDS_REVISION
    else:
        verdict = MemoryCompactReviewVerdict.PASS
    return MemoryCompactReviewResult(
        compact_id=compact.id,
        verdict=verdict,
        total_score=total_score,
        max_score=len(_RUBRIC) * 2,
        scores=scores,
        missing_refs=missing_refs,
        contradictions=contradictions,
        stale_reasons=stale_reasons,
        recommended_actions=_recommended_actions(
            verdict=verdict,
            scores=scores,
            missing_refs=missing_refs,
            stale_reasons=stale_reasons,
            contradictions=contradictions,
        ),
    )
