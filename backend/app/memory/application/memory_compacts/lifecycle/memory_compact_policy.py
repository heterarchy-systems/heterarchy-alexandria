"""Memory Compact CURRENT lifecycle validation policy."""

from __future__ import annotations

import re

from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactReviewResult,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
)
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactValidationError

_CURRENT_REQUIRED_SECTIONS: tuple[tuple[str, str], ...] = (
    ("durable decisions", "Durable Decisions"),
    ("current state", "Current State"),
    ("risks and blockers", "Risks and Blockers"),
    ("next actions", "Next Actions"),
    ("coverage", "Coverage"),
    ("evidence summary", "Evidence Summary"),
)


def missing_current_sections(markdown_body: str) -> list[str]:
    """Return required CURRENT headings absent from one Markdown body.

    Args:
        markdown_body: Candidate Memory Compact Markdown.

    Returns:
        Human-readable missing section names.
    """
    headings = {
        _normalize_section_heading(match.group(1))
        for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", markdown_body, re.MULTILINE)
    }
    return [
        display
        for normalized, display in _CURRENT_REQUIRED_SECTIONS
        if normalized not in headings
    ]


def ensure_review_passes(review: MemoryCompactReviewResult) -> None:
    """Reject a Memory Compact review that does not pass the rubric.

    Args:
        review: Structured Memory Compact review result.
    """
    if review.verdict is MemoryCompactReviewVerdict.PASS:
        return
    reasons = [*review.missing_refs, *review.contradictions, *review.stale_reasons]
    if not reasons:
        reasons = list(review.recommended_actions)
    reason_text = ",".join(reasons) if reasons else "rubric_not_passed"
    raise MemoryCompactValidationError(
        f"Current memory compact review failed: {review.verdict.value}: {reason_text}"
    )


def _normalize_section_heading(value: str) -> str:
    """Normalize section heading.

    Args:
        value: Value being processed.

    Returns:
        Normalized section heading.
    """
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
