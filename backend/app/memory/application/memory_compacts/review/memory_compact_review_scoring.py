"""Rubric definitions and Markdown scoring for Memory Compact review."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactRubricScore,
)
from app.memory.application.memory_compacts.review.memory_compact_review_evidence import (
    unlinked_source_refs,
)
from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)


@dataclass(frozen=True, slots=True)
class RubricSpec:
    """Specification for one Memory Compact review rubric criterion."""

    code: str
    label: str
    required: bool


RUBRIC: tuple[RubricSpec, ...] = (
    RubricSpec("durable_decisions", "Durable Decisions", True),
    RubricSpec("current_state", "Current State", True),
    RubricSpec("risks_blockers", "Risks and Blockers", True),
    RubricSpec("next_actions", "Next Actions", True),
    RubricSpec("evidence_completeness", "Evidence Completeness", True),
    RubricSpec("project_isolation", "Project Isolation", True),
    RubricSpec("freshness", "Freshness", True),
    RubricSpec("concision", "Concision", False),
    RubricSpec("contradiction_handling", "Contradiction Handling", True),
    RubricSpec("actionability", "Actionability", False),
)
REQUIRED_TWO_SCORE_CODES = frozenset(
    {"evidence_completeness", "current_state", "project_isolation"}
)


def score_rubric_item(
    spec: RubricSpec,
    compact: MemoryCompact,
    sections: dict[str, str],
    missing_refs: tuple[str, ...],
    stale_reasons: tuple[str, ...],
    contradictions: tuple[str, ...],
) -> MemoryCompactRubricScore:
    """Evaluate one rubric criterion against the compact and extracted sections.

    Args:
        spec: Rubric criterion specification to evaluate.
        compact: Memory Compact under review.
        sections: Normalized heading-to-body section mapping.
        missing_refs: Missing or incomplete source reference reasons.
        stale_reasons: Stale or unavailable source observation reasons.
        contradictions: Blocking contradiction codes detected in the body.

    Returns:
        Scored rubric item with explanation reason codes.
    """
    if spec.code == "evidence_completeness":
        score, reasons = _RubricItemScorer.score_evidence_completeness(
            sections=sections,
            source_refs=compact.source_refs,
            missing_refs=missing_refs,
        )
    elif spec.code == "project_isolation":
        score, reasons = _RubricItemScorer.score_project_isolation(compact, sections)
    elif spec.code == "freshness":
        score = 0 if stale_reasons else 2
        reasons = stale_reasons
    elif spec.code == "concision":
        score, reasons = _RubricItemScorer.score_concision(compact.markdown_body)
    elif spec.code == "contradiction_handling":
        score = 0 if contradictions else 2
        reasons = contradictions
    elif spec.code == "actionability":
        score, reasons = _RubricItemScorer.score_actionability(sections)
    else:
        score, reasons = _RubricItemScorer.score_required_section(spec.code, sections)
    return MemoryCompactRubricScore(
        code=spec.code,
        label=spec.label,
        score=score,
        required=spec.required,
        reasons=reasons,
    )


class _RubricItemScorer:
    """Evaluate individual rubric dimensions for Memory Compact review."""

    @staticmethod
    def score_required_section(
        code: str,
        sections: dict[str, str],
    ) -> tuple[int, tuple[str, ...]]:
        """Score presence and minimum depth of a required Markdown section.

        Args:
            code: Canonical section key to inspect.
            sections: Normalized heading-to-body section mapping.

        Returns:
            Tuple of numeric score (0-2) and any deficiency reason codes.
        """
        section = sections.get(code, "").strip()
        if not section:
            return 0, (f"{code}_missing",)
        if len(_words(section)) < 3:
            return 1, (f"{code}_too_thin",)
        return 2, ()

    @staticmethod
    def score_project_isolation(
        compact: MemoryCompact,
        sections: dict[str, str],
    ) -> tuple[int, tuple[str, ...]]:
        """Score whether project-scoped compacts explicitly match their project.

        Args:
            compact: Memory Compact under review.
            sections: Normalized heading-to-body section mapping.

        Returns:
            Tuple of numeric score (0-2) and any scope mismatch reason codes.
        """
        if compact.project is None:
            return 2, ()
        body = "\n".join(sections.values()).lower()
        project = compact.project.lower()
        project_lines = [
            line.strip().lower()
            for line in body.splitlines()
            if line.strip().startswith("- project:")
            or line.strip().startswith("project:")
        ]
        if any(project not in line for line in project_lines):
            return 0, ("project_scope_mismatch",)
        if project in body:
            return 2, ()
        return 1, ("project_scope_not_explicit",)

    @staticmethod
    def score_concision(markdown_body: str) -> tuple[int, tuple[str, ...]]:
        """Score whether the Markdown body stays within bounded length thresholds.

        Args:
            markdown_body: Full Markdown body of the compact.

        Returns:
            Tuple of numeric score (0-2) and any verbosity reason codes.
        """
        if len(markdown_body) > 12_000:
            return 0, ("compact_too_long",)
        if len(markdown_body) > 8_000:
            return 1, ("compact_verbose",)
        return 2, ()

    @staticmethod
    def score_actionability(sections: dict[str, str]) -> tuple[int, tuple[str, ...]]:
        """Score whether the Next Actions section contains concrete content.

        Args:
            sections: Normalized heading-to-body section mapping.

        Returns:
            Tuple of numeric score (0-2) and any actionability reason codes.
        """
        next_actions = sections.get("next_actions", "")
        if not next_actions.strip():
            return 0, ("next_actions_missing",)
        if len(_words(next_actions)) < 3:
            return 1, ("next_actions_too_thin",)
        return 2, ()

    @staticmethod
    def score_evidence_completeness(
        sections: dict[str, str],
        source_refs: tuple[MemoryCompactSourceRef, ...],
        missing_refs: tuple[str, ...],
    ) -> tuple[int, tuple[str, ...]]:
        """Score whether all declared source references are valid and linked.

        Args:
            sections: Normalized heading-to-body section mapping.
            source_refs: Declared source references on the compact.
            missing_refs: Precomputed missing or broken reference reasons.

        Returns:
            Tuple of numeric score (0-2) and any evidence linkage reason codes.
        """
        if missing_refs:
            return 0, missing_refs
        evidence_summary = sections.get("evidence_summary", "")
        unlinked = unlinked_source_refs(evidence_summary, source_refs)
        if unlinked:
            return 1, unlinked
        return 2, ()


def markdown_sections(markdown_body: str) -> dict[str, str]:
    """Collect section bodies through descendants until a peer or ancestor heading.

    Args:
        markdown_body: Full Markdown body of the compact.

    Returns:
        Mapping from normalized section key to collected section text.
    """
    sections: dict[str, list[str]] = {}
    active_sections: list[tuple[int, str]] = []
    for line in markdown_body.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            level = len(match.group(1))
            while active_sections and active_sections[-1][0] >= level:
                active_sections.pop()
            key = _section_key(match.group(2))
            sections.setdefault(key, [])
            active_sections.append((level, key))
            continue
        # Descendant body belongs to each ancestor; headings alone are not body.
        for key in {key for _, key in active_sections}:
            sections[key].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def _section_key(heading: str) -> str:
    """Normalize a Markdown heading into a canonical rubric section key.

    Args:
        heading: Raw Markdown heading text without leading hash marks.

    Returns:
        Canonical snake_case section key.
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
    """Tokenize word-like alphanumeric and Hangul segments from text.

    Args:
        value: Input text to tokenize.

    Returns:
        List of extracted word tokens.
    """
    return re.findall(r"[\w가-힣]+", value)
