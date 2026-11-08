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


def missing_ref_reasons(
    source_refs: tuple[MemoryCompactSourceRef, ...],
) -> tuple[str, ...]:
    """Identify missing, incomplete, or broken source reference declarations.

    Args:
        source_refs: Declared source references on the compact.

    Returns:
        Tuple of missing or broken source-reference reason codes.
    """
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


def unlinked_source_refs(
    evidence_summary: str,
    source_refs: tuple[MemoryCompactSourceRef, ...],
) -> tuple[str, ...]:
    """Find declared source references that are not cited in the evidence summary.

    Args:
        evidence_summary: Extracted Markdown text of the Evidence Summary section.
        source_refs: Declared source references on the compact.

    Returns:
        Tuple of unlinked source-reference reason codes.
    """
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


def stale_reasons(
    source_refs: tuple[MemoryCompactSourceRef, ...],
    source_observations: tuple[MemoryCompactSourceObservation, ...],
) -> tuple[str, ...]:
    """Compare declared source hashes against current source observations.

    Args:
        source_refs: Declared source references on the compact.
        source_observations: Current canonical source observations.

    Returns:
        Tuple of staleness or unavailability reason codes.
    """
    observations = {
        (observation.source_id, observation.detail_path): observation
        for observation in source_observations
    }
    reasons: list[str] = []
    for source_ref in source_refs:
        observation = observations.get((source_ref.source_id, source_ref.detail_path))
        if observation is None:
            observation = observations.get((source_ref.source_id, None))
        if observation is not None and not observation.available:
            reason = observation.unavailable_reason or "source_unavailable"
            reasons.append(f"source_unavailable:{source_ref.source_id}:{reason}")
            continue
        if (
            observation is not None
            and source_ref.source_hash is not None
            and observation.current_source_hash is None
        ):
            reasons.append(f"source_hash_unavailable:{source_ref.source_id}")
            continue
        if (
            observation is not None
            and source_ref.source_hash is not None
            and observation.current_source_hash != source_ref.source_hash
        ):
            reasons.append(f"source_hash_mismatch:{source_ref.source_id}")
    return tuple(reasons)


def contradictions(markdown_body: str) -> tuple[str, ...]:
    """Detect blocking contradiction markers in the compact Markdown body.

    Args:
        markdown_body: Full Markdown body of the compact under review.

    Returns:
        Tuple of normalized contradiction marker codes found in the body.
    """
    body = markdown_body.lower()
    return tuple(
        pattern.replace(" ", "_")
        for pattern in _BLOCKING_CONTRADICTION_PATTERNS
        if pattern in body
    )


def recommended_actions(
    verdict: MemoryCompactReviewVerdict,
    scores: tuple[MemoryCompactRubricScore, ...],
    missing_refs: tuple[str, ...],
    stale_reasons: tuple[str, ...],
    contradictions: tuple[str, ...],
) -> tuple[str, ...]:
    """Derive deterministic remediation or promotion actions from review findings.

    Args:
        verdict: Computed review verdict for the compact.
        scores: Rubric item score breakdown.
        missing_refs: Missing or incomplete source reference reasons.
        stale_reasons: Source hash mismatch or unavailability reasons.
        contradictions: Blocking contradiction markers found in the body.

    Returns:
        Tuple of recommended next action codes.
    """
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
