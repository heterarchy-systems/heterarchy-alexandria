"""Evidence linkage, freshness, contradiction, and action policies for compact review."""

from __future__ import annotations

from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactRubricScore,
    MemoryCompactSourceObservation,
)
from app.memory.domain.entities.memory_compact import (
    MemoryCompactSourceRef,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
)

_BLOCKING_CONTRADICTION_PATTERNS = (
    "unresolved contradiction",
    "blocking contradiction",
    "contradiction unresolved",
    "미해결 모순",
    "차단급 모순",
)


def _missing_ref_reasons(
    source_refs: tuple[MemoryCompactSourceRef, ...],
) -> tuple[str, ...]:
    if not source_refs:
        return ("source_refs_missing",)
    reasons: list[str] = []
    for source_ref in source_refs:
        if (
            not source_ref.source_type.strip()
            or not source_ref.source_id.strip()
            or not source_ref.title.strip()
            or not source_ref.detail_path.strip()
        ):
            reasons.append(f"source_ref_incomplete:{source_ref.source_id or 'unknown'}")
        if source_ref.detail_path.strip().lower().startswith(("missing:", "broken:")):
            reasons.append(f"source_ref_broken:{source_ref.source_id}")
    return tuple(reasons)


def _unlinked_source_refs(
    evidence_summary: str,
    source_refs: tuple[MemoryCompactSourceRef, ...],
) -> tuple[str, ...]:
    normalized_summary = evidence_summary.lower()
    reasons: list[str] = []
    for source_ref in source_refs:
        markers = (
            source_ref.source_id.strip().lower(),
            source_ref.detail_path.strip().lower(),
            source_ref.title.strip().lower(),
        )
        if not any(marker and marker in normalized_summary for marker in markers):
            reasons.append(f"source_ref_unlinked:{source_ref.source_id}")
    return tuple(reasons)


def _stale_reasons(
    source_refs: tuple[MemoryCompactSourceRef, ...],
    source_observations: tuple[MemoryCompactSourceObservation, ...],
) -> tuple[str, ...]:
    observations = {
        _observation_key(observation): observation
        for observation in source_observations
        if observation.current_source_hash is not None
    }
    reasons: list[str] = []
    for source_ref in source_refs:
        observation = observations.get(_source_ref_key(source_ref))
        if observation is None:
            observation = observations.get((source_ref.source_id, None))
        if (
            observation is not None
            and source_ref.source_hash is not None
            and observation.current_source_hash != source_ref.source_hash
        ):
            reasons.append(f"source_hash_mismatch:{source_ref.source_id}")
    return tuple(reasons)


def _contradictions(markdown_body: str) -> tuple[str, ...]:
    body = markdown_body.lower()
    return tuple(
        pattern.replace(" ", "_")
        for pattern in _BLOCKING_CONTRADICTION_PATTERNS
        if pattern in body
    )


def _recommended_actions(
    verdict: MemoryCompactReviewVerdict,
    scores: tuple[MemoryCompactRubricScore, ...],
    missing_refs: tuple[str, ...],
    stale_reasons: tuple[str, ...],
    contradictions: tuple[str, ...],
) -> tuple[str, ...]:
    actions: list[str] = []
    if missing_refs:
        actions.append("repair_source_refs")
    if stale_reasons:
        actions.append("refresh_source_evidence")
    if contradictions:
        actions.append("resolve_contradictions")
    evidence_score = next(
        score for score in scores if score.code == "evidence_completeness"
    )
    if evidence_score.score < 2 and not missing_refs:
        actions.append("improve_evidence_completeness")
    low_score_codes = [
        score.code
        for score in scores
        if score.required
        and score.score == 0
        and score.code
        not in {"evidence_completeness", "freshness", "contradiction_handling"}
    ]
    if low_score_codes:
        actions.append("revise_required_sections:" + ",".join(low_score_codes))
    if verdict is MemoryCompactReviewVerdict.PASS:
        actions.append("promote_or_keep_current")
    elif not actions:
        actions.append("revise_memory_compact")
    return tuple(actions)


def _source_ref_key(source_ref: MemoryCompactSourceRef) -> tuple[str, str | None]:
    return source_ref.source_id, source_ref.detail_path


def _observation_key(
    observation: MemoryCompactSourceObservation,
) -> tuple[str, str | None]:
    return observation.source_id, observation.detail_path
