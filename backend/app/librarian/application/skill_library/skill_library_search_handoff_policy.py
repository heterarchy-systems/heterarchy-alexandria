"""Search query, explanation, and handoff payload policy for skill lookup."""

from __future__ import annotations

from collections.abc import Sequence

from app.librarian.application.skill_library.skill_library_search_contracts import (
    SkillCapabilityBrief,
    SkillSearchCandidate,
)
from app.shared.types.extra_types import JSONObject, JSONValue


def _query_text(brief: SkillCapabilityBrief) -> str:
    """Execute query text.

    Args:
        brief: Brief used by this operation.

    Returns:
        str result produced by query text.
    """
    parts = [brief.capability, brief.task_goal, brief.environment]
    parts.extend(brief.required_tools)
    parts.extend(brief.success_criteria)
    return " ".join(part.strip() for part in parts if part and part.strip())


def _existing_skill_handoff(
    candidate: SkillSearchCandidate,
    brief: SkillCapabilityBrief,
) -> JSONObject:
    """Execute existing skill handoff.

    Args:
        candidate: Candidate used by this operation.
        brief: Brief used by this operation.

    Returns:
        JSONObject result produced by existing skill handoff.
    """
    evidence: list[JSONValue] = [
        {
            "url_or_path": url,
            "source_kind": "skill_evidence",
            "supports_claims": list(candidate.why_match),
        }
        for url in candidate.evidence
    ]
    return {
        "decision": "existing_skill_found",
        "skill": {
            "id": candidate.id,
            "title": candidate.title,
            "path": candidate.path,
            "status": candidate.status,
            "version": candidate.version,
            "risk_level": candidate.risk_level.value,
            "required_tools": list(candidate.required_tools),
        },
        "evidence": evidence,
        "reuse": {
            "sufficiency_score": candidate.sufficiency_score,
            "matched_terms": list(candidate.matched_terms),
            "why_match": list(candidate.why_match),
            "limitations": list(candidate.limitations),
        },
        "current_task": {
            "resume_summary": brief.task_goal or brief.capability,
            "next_steps": [
                f"Open and apply existing skill note: {candidate.path}",
                "Do not start librarian acquisition for this capability unless reuse fails.",
            ],
            "stop_condition": (
                "Stop when the existing skill has been applied to the current "
                "task or when a concrete limitation blocks reuse."
            ),
        },
    }


def _repair_handoff(error_message: str) -> JSONObject:
    """Execute repair handoff.

    Args:
        error_message: Error message used by this operation.

    Returns:
        JSONObject result produced by repair handoff.
    """
    return {
        "decision": "skill_search_repair_required",
        "repair": {
            "hint": (
                "Repair Obsidian search/readiness before starting skill acquisition "
                "so index failure is not mistaken for a missing skill."
            ),
            "error": error_message,
            "tools": [
                "alexandria_memory_steward_readiness",
                "alexandria_reindex_vault",
            ],
        },
    }


def _empty_decision_explanation(
    gaps: Sequence[str],
    limitations: Sequence[str],
) -> JSONObject:
    """Execute empty decision explanation.

    Args:
        gaps: Gaps used by this operation.
        limitations: Limitations used by this operation.

    Returns:
        JSONObject result produced by empty decision explanation.
    """
    return {
        "candidate_count": 0,
        "candidate_ids": [],
        "scores": [],
        "hard_gates": {},
        "match_reasons": {},
        "gaps": list(gaps),
        "limitations": list(limitations),
    }


def _decision_explanation(
    candidates: Sequence[SkillSearchCandidate],
    gaps: Sequence[str],
) -> JSONObject:
    """Execute decision explanation.

    Args:
        candidates: Candidates used by this operation.
        gaps: Gaps used by this operation.

    Returns:
        JSONObject result produced by decision explanation.
    """
    return {
        "candidate_count": len(candidates),
        "candidate_ids": [candidate.id for candidate in candidates],
        "scores": [
            {
                "id": candidate.id,
                "sufficiency_score": candidate.sufficiency_score,
            }
            for candidate in candidates
        ],
        "hard_gates": {candidate.id: candidate.hard_gates for candidate in candidates},
        "match_reasons": {
            candidate.id: list(candidate.why_match) for candidate in candidates
        },
        "gaps": list(gaps),
        "limitations": {
            candidate.id: list(candidate.limitations) for candidate in candidates
        },
    }


def _unique_gap_list(candidates: Sequence[SkillSearchCandidate]) -> list[str]:
    """Execute unique gap list.

    Args:
        candidates: Candidates used by this operation.

    Returns:
        list[str] result produced by unique gap list.
    """
    gaps: list[str] = []
    for candidate in candidates:
        for gap in candidate.gaps:
            if gap not in gaps:
                gaps.append(gap)
    return gaps
