"""Rubric definitions and Markdown scoring for Memory Compact review."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactRubricScore,
)
from app.memory.application.memory_compacts.review.memory_compact_review_evidence import (
    _unlinked_source_refs,
)
from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)


@dataclass(frozen=True, slots=True)
class _RubricSpec:
    code: str
    label: str
    required: bool


_RUBRIC: tuple[_RubricSpec, ...] = (
    _RubricSpec("durable_decisions", "Durable Decisions", True),
    _RubricSpec("current_state", "Current State", True),
    _RubricSpec("risks_blockers", "Risks and Blockers", True),
    _RubricSpec("next_actions", "Next Actions", True),
    _RubricSpec("evidence_completeness", "Evidence Completeness", True),
    _RubricSpec("project_isolation", "Project Isolation", True),
    _RubricSpec("freshness", "Freshness", True),
    _RubricSpec("concision", "Concision", False),
    _RubricSpec("contradiction_handling", "Contradiction Handling", True),
    _RubricSpec("actionability", "Actionability", False),
)
_REQUIRED_TWO_SCORE_CODES = frozenset(
    {"evidence_completeness", "current_state", "project_isolation"}
)


def _score_rubric_item(
    spec: _RubricSpec,
    compact: MemoryCompact,
    sections: dict[str, str],
    missing_refs: tuple[str, ...],
    stale_reasons: tuple[str, ...],
    contradictions: tuple[str, ...],
) -> MemoryCompactRubricScore:
    """Execute score rubric item.

    Args:
        spec: Spec used by this operation.
        compact: Compact used by this operation.
        sections: Sections used by this operation.
        missing_refs: Missing refs used by this operation.
        stale_reasons: Stale reasons used by this operation.
        contradictions: Contradictions used by this operation.

    Returns:
        MemoryCompactRubricScore result produced by score rubric item.
    """
    if spec.code == "evidence_completeness":
        score, reasons = _score_evidence_completeness(
            sections=sections,
            source_refs=compact.source_refs,
            missing_refs=missing_refs,
        )
    elif spec.code == "project_isolation":
        score, reasons = _score_project_isolation(compact, sections)
    elif spec.code == "freshness":
        score = 0 if stale_reasons else 2
        reasons = stale_reasons
    elif spec.code == "concision":
        score, reasons = _score_concision(compact.markdown_body)
    elif spec.code == "contradiction_handling":
        score = 0 if contradictions else 2
        reasons = contradictions
    elif spec.code == "actionability":
        score, reasons = _score_actionability(sections)
    else:
        score, reasons = _score_required_section(spec.code, sections)
    return MemoryCompactRubricScore(
        code=spec.code,
        label=spec.label,
        score=score,
        required=spec.required,
        reasons=reasons,
    )


def _score_required_section(
    code: str,
    sections: dict[str, str],
) -> tuple[int, tuple[str, ...]]:
    """Execute score required section.

    Args:
        code: Code used by this operation.
        sections: Sections used by this operation.

    Returns:
        tuple[int, tuple[str, ...]] result produced by score required section.
    """
    section = sections.get(code, "").strip()
    if not section:
        return 0, (f"{code}_missing",)
    if len(_words(section)) < 3:
        return 1, (f"{code}_too_thin",)
    return 2, ()


def _score_project_isolation(
    compact: MemoryCompact,
    sections: dict[str, str],
) -> tuple[int, tuple[str, ...]]:
    """Execute score project isolation.

    Args:
        compact: Compact used by this operation.
        sections: Sections used by this operation.

    Returns:
        tuple[int, tuple[str, ...]] result produced by score project isolation.
    """
    if compact.project is None:
        return 2, ()
    body = "\n".join(sections.values()).lower()
    project = compact.project.lower()
    project_lines = [
        line.strip().lower()
        for line in body.splitlines()
        if line.strip().startswith("- project:") or line.strip().startswith("project:")
    ]
    if any(project not in line for line in project_lines):
        return 0, ("project_scope_mismatch",)
    if project in body:
        return 2, ()
    return 1, ("project_scope_not_explicit",)


def _score_concision(markdown_body: str) -> tuple[int, tuple[str, ...]]:
    """Execute score concision.

    Args:
        markdown_body: Markdown body used by this operation.

    Returns:
        tuple[int, tuple[str, ...]] result produced by score concision.
    """
    if len(markdown_body) > 12_000:
        return 0, ("compact_too_long",)
    if len(markdown_body) > 8_000:
        return 1, ("compact_verbose",)
    return 2, ()


def _score_actionability(sections: dict[str, str]) -> tuple[int, tuple[str, ...]]:
    """Execute score actionability.

    Args:
        sections: Sections used by this operation.

    Returns:
        tuple[int, tuple[str, ...]] result produced by score actionability.
    """
    next_actions = sections.get("next_actions", "")
    if not next_actions.strip():
        return 0, ("next_actions_missing",)
    if len(_words(next_actions)) < 3:
        return 1, ("next_actions_too_thin",)
    return 2, ()


def _score_evidence_completeness(
    sections: dict[str, str],
    source_refs: tuple[MemoryCompactSourceRef, ...],
    missing_refs: tuple[str, ...],
) -> tuple[int, tuple[str, ...]]:
    """Execute score evidence completeness.

    Args:
        sections: Sections used by this operation.
        source_refs: Source refs used by this operation.
        missing_refs: Missing refs used by this operation.

    Returns:
        tuple[int, tuple[str, ...]] result produced by score evidence completeness.
    """
    if missing_refs:
        return 0, missing_refs
    evidence_summary = sections.get("evidence_summary", "")
    unlinked = _unlinked_source_refs(evidence_summary, source_refs)
    if unlinked:
        return 1, unlinked
    return 2, ()


def _markdown_sections(markdown_body: str) -> dict[str, str]:
    """Execute markdown sections.

    Args:
        markdown_body: Markdown body used by this operation.

    Returns:
        dict[str, str] result produced by markdown sections.
    """
    sections: dict[str, list[str]] = {}
    current_key: str | None = None
    for line in markdown_body.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            current_key = _section_key(match.group(1))
            sections.setdefault(current_key, [])
            continue
        if current_key is not None:
            sections[current_key].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def _section_key(heading: str) -> str:
    """Execute section key.

    Args:
        heading: Heading used by this operation.

    Returns:
        str result produced by section key.
    """
    normalized = re.sub(r"[^a-z0-9]+", " ", heading.lower()).strip()
    if normalized == "durable decisions":
        return "durable_decisions"
    if normalized == "current state":
        return "current_state"
    if normalized in {"risks and blockers", "risks blockers"}:
        return "risks_blockers"
    if normalized == "next actions":
        return "next_actions"
    if normalized == "evidence summary":
        return "evidence_summary"
    return normalized.replace(" ", "_")


def _words(value: str) -> list[str]:
    """Execute words.

    Args:
        value: Value being processed.

    Returns:
        list[str] result produced by words.
    """
    return re.findall(r"[\w가-힣]+", value)
