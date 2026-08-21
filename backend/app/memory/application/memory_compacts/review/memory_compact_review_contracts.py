"""Structured contracts returned by deterministic Memory Compact review."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompactSourceObservation:
    """Observed current evidence state for one compact source ref."""

    source_id: str
    detail_path: str | None = None
    current_source_hash: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompactRubricScore:
    """Single rubric item score for a Memory Compact review."""

    code: str
    label: str
    score: int
    required: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompactReviewResult:
    """Structured librarian review result for a Memory Compact."""

    compact_id: str
    verdict: MemoryCompactReviewVerdict
    total_score: int
    max_score: int
    scores: tuple[MemoryCompactRubricScore, ...]
    missing_refs: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    stale_reasons: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
