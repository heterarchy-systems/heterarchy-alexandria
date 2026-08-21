"""Candidate parsing, hard gates, and deterministic scoring for skill lookup."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.librarian.application.skill_library.skill_library_search_contracts import (
    SkillCapabilityBrief,
    SkillSearchCandidate,
)
from app.librarian.domain.event_enum.skill_acquisition_enums import RiskLevel
from app.obsidian.domain.entities.obsidian_note import ObsidianSearchHit
from app.shared.types.extra_types import JSONObject, JSONValue


def _dedupe_candidates(
    hits: list[ObsidianSearchHit],
    brief: SkillCapabilityBrief,
) -> list[SkillSearchCandidate]:
    candidates: list[SkillSearchCandidate] = []
    seen: set[str] = set()
    for hit in hits:
        note = hit.note
        if note.note_id in seen:
            continue
        seen.add(note.note_id)
        status = _skill_status(note.status, note.frontmatter)
        if status in {"archived", "deprecated", "superseded"}:
            continue
        candidates.append(_candidate_from_hit(hit, brief, status))
    candidates.sort(
        key=lambda candidate: (-candidate.sufficiency_score, -candidate.score)
    )
    return candidates


def _candidate_from_hit(
    hit: ObsidianSearchHit,
    brief: SkillCapabilityBrief,
    status: str,
) -> SkillSearchCandidate:
    note = hit.note
    required_tools = _string_list(note.frontmatter.get("required_tools"))
    risk_level = _risk_level(note.frontmatter.get("risk_level"))
    risk_tolerance = _risk_level(brief.risk_tolerance)
    evidence = _string_list(note.frontmatter.get("evidence_urls"))
    if not evidence:
        evidence = _evidence_from_body(note.body)
    matched_terms = _matched_terms(brief, f"{note.title}\n{hit.excerpt}\n{note.body}")
    gaps: list[str] = []
    why_match: list[str] = []

    if status != "active":
        gaps.append(f"skill status is {status}; human review is required before reuse")
    else:
        why_match.append("skill status is active")

    missing_tools = sorted(
        set(_lower_items(brief.required_tools)) - set(_lower_items(required_tools))
    )
    if missing_tools:
        gaps.append("missing required tools: " + ", ".join(missing_tools))
    else:
        why_match.append("required tools are compatible")

    if _risk_rank(risk_level) > _risk_rank(risk_tolerance):
        gaps.append(
            f"risk level {risk_level.value} exceeds tolerance {risk_tolerance.value}"
        )
    else:
        why_match.append("risk level is within tolerance")

    if not _has_procedure(note.body):
        gaps.append("skill body lacks a concrete Procedure section")
    else:
        why_match.append("body includes a concrete Procedure section")

    if not matched_terms:
        gaps.append(
            "candidate matched search index but no brief terms were found in note"
        )
    else:
        why_match.append(
            "candidate matched brief terms: " + ", ".join(matched_terms[:5])
        )

    if not evidence:
        gaps.append("skill lacks evidence links")
    else:
        why_match.append("skill includes evidence links")

    score = _candidate_score(
        matched_terms=tuple(matched_terms),
        has_procedure=_has_procedure(note.body),
        has_evidence=bool(evidence),
        project_match=brief.project is None or brief.project == note.project,
        tool_match=not missing_tools,
    )
    sufficiency_score = max(0, min(10, score - (2 * len(gaps))))
    limitations = list(gaps)
    recommended_action = (
        "Reuse this skill for the current task."
        if not gaps and sufficiency_score >= 8
        else "Use as context for librarian acquisition; do not auto-apply as sufficient."
    )
    return SkillSearchCandidate(
        id=note.note_id,
        path=note.relative_path,
        title=note.title,
        status=status,
        version=_optional_string(note.frontmatter.get("version")),
        project=note.project,
        required_tools=tuple(required_tools),
        risk_level=risk_level,
        evidence=tuple(evidence),
        matched_terms=tuple(matched_terms),
        limitations=tuple(limitations),
        score=hit.score,
        sufficiency_score=sufficiency_score,
        hard_gates=_hard_gates(
            status=status,
            missing_tools=missing_tools,
            risk_level=risk_level,
            risk_tolerance=risk_tolerance,
            has_procedure=_has_procedure(note.body),
            matched_terms=tuple(matched_terms),
            has_evidence=bool(evidence),
        ),
        why_match=tuple(why_match),
        gaps=tuple(gaps),
        recommended_action=recommended_action,
    )


def _hard_gates(
    status: str,
    missing_tools: Sequence[str],
    risk_level: RiskLevel,
    risk_tolerance: RiskLevel,
    has_procedure: bool,
    matched_terms: Sequence[str],
    has_evidence: bool,
) -> JSONObject:
    return {
        "active_status": {
            "passed": status == "active",
            "actual": status,
            "required": "active",
        },
        "required_tools": {
            "passed": not missing_tools,
            "missing": list(missing_tools),
        },
        "risk_tolerance": {
            "passed": _risk_rank(risk_level) <= _risk_rank(risk_tolerance),
            "actual": risk_level.value,
            "maximum": risk_tolerance.value,
        },
        "procedure_section": {
            "passed": has_procedure,
        },
        "brief_match": {
            "passed": bool(matched_terms),
            "matched_terms": list(matched_terms),
        },
        "evidence": {
            "passed": has_evidence,
        },
    }


def _candidate_score(
    matched_terms: Sequence[str],
    has_procedure: bool,
    has_evidence: bool,
    project_match: bool,
    tool_match: bool,
) -> int:
    score = 0
    score += min(2, len(matched_terms))
    score += 2 if project_match else 0
    score += 2 if has_procedure else 0
    score += 2 if tool_match else 0
    score += 2 if has_evidence else 1
    return score


def _skill_status(status: str, frontmatter: JSONObject) -> str:
    if isinstance(frontmatter, dict):
        for key in ("skill_status", "status", "requested_status"):
            value = frontmatter.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
    return status.strip().lower()


def _risk_level(value: JSONValue) -> RiskLevel:
    if isinstance(value, RiskLevel):
        return value
    if isinstance(value, str):
        normalized = value.strip().upper()
        for risk in RiskLevel:
            if normalized == risk.value:
                return risk
    return RiskLevel.LOW


def _risk_rank(value: RiskLevel) -> int:
    return {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}[value]


def _has_procedure(body: str) -> bool:
    match = re.search(
        r"^##+\s+.*(Procedure|단계별 절차).*$",
        body,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if match is None:
        return False
    section = body[match.end() :]
    next_heading = re.search(r"^##+\s+", section, flags=re.MULTILINE)
    if next_heading is not None:
        section = section[: next_heading.start()]
    stripped = section.strip()
    return bool(stripped and stripped != "- none provided")


def _matched_terms(brief: SkillCapabilityBrief, haystack: str) -> list[str]:
    needles = [brief.capability, *brief.required_tools]
    if brief.environment:
        needles.append(brief.environment)
    if brief.task_goal:
        needles.extend(_important_words(brief.task_goal))
    haystack_lower = haystack.lower()
    matched: list[str] = []
    for needle in needles:
        normalized = needle.strip().lower()
        if normalized and normalized in haystack_lower and normalized not in matched:
            matched.append(normalized)
    return matched


def _important_words(value: str) -> list[str]:
    return list(re.findall(r"[A-Za-z0-9_-]{4,}", value.lower())[:8])


def _evidence_from_body(body: str) -> list[str]:
    urls = re.findall(r"https?://[^\s)]+", body)
    return urls[:5]


def _string_list(value: JSONValue) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        normalized = item.strip() if isinstance(item, str) else ""
        if normalized and normalized not in items:
            items.append(normalized)
    return items


def _lower_items(values: Sequence[str]) -> list[str]:
    return [value.strip().lower() for value in values if value.strip()]


def _optional_string(value: JSONValue) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
