"""Versioned deterministic adaptive retrieval planning for Context recall."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.memory.domain.event_enum.context_enums import (
    ContextRetrievalFusionProfile,
    ContextRetrievalIntent,
    MemoryFunction,
    RagStrategy,
)

ADAPTIVE_RETRIEVAL_PROFILE_VERSION: Final[str] = "adaptive-retrieval-v1"
_HYBRID_CANDIDATE_MULTIPLIER: Final[int] = 6
_MAX_CANDIDATE_BUDGET: Final[int] = 50
_GRAPH_ORIENTED_DEPTH: Final[int] = 2
_TITLE_LIKE_MAX_TOKENS: Final[int] = 8
_TITLE_LIKE_MAX_CHARACTERS: Final[int] = 96
_QUERY_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-z가-힣_./:+-]+")
_DATE_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")

_TEMPORAL_MARKERS: Final[tuple[str, ...]] = (
    "현재 상태",
    "최신",
    "지금",
    "최종",
    "승인된",
    "current state",
    "latest",
    "right now",
    "final state",
    "final seal",
)

_EXPERIENTIAL_MARKERS: Final[tuple[str, ...]] = (
    "예전에",
    "전에 비슷",
    "이전에 비슷",
    "과거에 비슷",
    "경험",
    "교훈",
    "원인이",
    "고쳤",
    "문제와 해결",
    "이유와 결과",
    "검증한 결과",
    "실제 성능을 검증",
    "다시 겪지",
    "장애",
    "버그",
    "incident",
    "previous issue",
    "similar issue",
    "lessons learned",
    "root cause",
    "bug",
)

_PROCEDURAL_MARKERS: Final[tuple[str, ...]] = (
    "순서",
    "절차",
    "세팅",
    "재현하려",
    "따라가",
    "작업 전에",
    "어떻게 진행",
    "진행 방법",
    "방법 알려",
    "how to",
    "steps",
    "procedure",
    "setup",
    "reproduce",
)

_GRAPH_MARKERS: Final[tuple[str, ...]] = (
    "무엇과 관련",
    "어떤 관계",
    "관계가",
    "관계 evidence",
    "연결되어",
    "연결된",
    "연결해",
    "영향 관계",
    "graph",
    "graph path",
    "evidence chain",
    "lineage",
    "relation evidence",
    "related to",
    "relationship",
    "dependency graph",
    "impact graph",
)

_SEMANTIC_MARKERS: Final[tuple[str, ...]] = (
    "알려줘",
    "설명해",
    "찾아줘",
    "무엇",
    "뭐가",
    "왜",
    "what",
    "why",
    "explain",
    "find",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextRetrievalPlan:
    """One immutable Python-owned retrieval policy resolved before lane execution."""

    profile_version: str
    intent: ContextRetrievalIntent
    strategy: RagStrategy
    lexical_enabled: bool
    vector_enabled: bool
    graph_enabled: bool
    fts_budget: int
    vector_budget: int
    graph_depth: int
    candidate_multiplier: int
    fusion_profile: ContextRetrievalFusionProfile
    top_k: int
    preferred_memory_functions: tuple[MemoryFunction, ...]
    temporal_current_preference: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject internally inconsistent plans before execution."""
        if self.strategy is RagStrategy.AUTO:
            raise ValueError(
                "adaptive plan strategy must resolve to a fixed retrieval lane"
            )
        if self.top_k < 1 or self.top_k > 50:
            raise ValueError("adaptive plan top_k must be 1..50")
        if self.fts_budget < 0 or self.vector_budget < 0:
            raise ValueError("adaptive plan budgets must be non-negative")
        if self.graph_depth not in (0, _GRAPH_ORIENTED_DEPTH):
            raise ValueError("adaptive plan graph_depth must be 0 or 2 in v1")
        if self.candidate_multiplier < 1:
            raise ValueError("adaptive plan candidate_multiplier must be positive")
        if self.strategy is RagStrategy.FTS_ONLY and (
            not self.lexical_enabled or self.vector_enabled or self.vector_budget != 0
        ):
            raise ValueError("FTS_ONLY adaptive plan has inconsistent lane settings")
        if self.strategy is RagStrategy.VECTOR_ONLY and (
            self.lexical_enabled or not self.vector_enabled or self.fts_budget != 0
        ):
            raise ValueError("VECTOR_ONLY adaptive plan has inconsistent lane settings")
        if self.strategy is RagStrategy.HYBRID and not (
            self.lexical_enabled and self.vector_enabled
        ):
            raise ValueError("HYBRID adaptive plan must enable both primary lanes")
        if self.graph_enabled != (self.graph_depth > 0):
            raise ValueError("adaptive plan graph enablement and depth disagree")


def build_context_retrieval_plan(
    query: str,
    top_k: int,
    caller_memory_functions: tuple[MemoryFunction, ...] = (),
) -> ContextRetrievalPlan:
    """Build one deterministic v1 retrieval plan without external model calls.

    Args:
        query: Validated non-empty search query.
        top_k: Requested final result count.
        caller_memory_functions: Explicit caller preference that outranks inferred roles.

    Returns:
        Immutable adaptive retrieval plan.
    """
    normalized = _normalized_query(query)
    intent, reason = _classify_intent(query, normalized)
    graph_requested = _contains_marker(normalized, _GRAPH_MARKERS)
    preferred = (
        caller_memory_functions
        if caller_memory_functions
        else _inferred_memory_functions(intent)
    )
    graph_enabled = intent is ContextRetrievalIntent.GRAPH_ORIENTED or graph_requested
    if intent is ContextRetrievalIntent.EXACT_OR_TITLE:
        return ContextRetrievalPlan(
            profile_version=ADAPTIVE_RETRIEVAL_PROFILE_VERSION,
            intent=intent,
            strategy=RagStrategy.FTS_ONLY,
            lexical_enabled=True,
            vector_enabled=False,
            graph_enabled=False,
            fts_budget=top_k,
            vector_budget=0,
            graph_depth=0,
            candidate_multiplier=1,
            fusion_profile=ContextRetrievalFusionProfile.NONE,
            top_k=top_k,
            preferred_memory_functions=preferred,
            temporal_current_preference=False,
            reasons=(reason, "exact_or_title_prefers_lexical_lane"),
        )
    budget = _hybrid_budget(top_k)
    return ContextRetrievalPlan(
        profile_version=ADAPTIVE_RETRIEVAL_PROFILE_VERSION,
        intent=intent,
        strategy=RagStrategy.HYBRID,
        lexical_enabled=True,
        vector_enabled=True,
        graph_enabled=graph_enabled,
        fts_budget=budget,
        vector_budget=budget,
        graph_depth=_GRAPH_ORIENTED_DEPTH if graph_enabled else 0,
        candidate_multiplier=_HYBRID_CANDIDATE_MULTIPLIER,
        fusion_profile=ContextRetrievalFusionProfile.RECIPROCAL_RANK_V1,
        top_k=top_k,
        preferred_memory_functions=preferred,
        temporal_current_preference=(
            intent is ContextRetrievalIntent.TEMPORAL_CURRENT_STATE
        ),
        reasons=(reason, "hybrid_preserves_lexical_and_semantic_recall"),
    )


def _classify_intent(
    raw_query: str,
    normalized_query: str,
) -> tuple[ContextRetrievalIntent, str]:
    """Classify one query using ordered deterministic v1 markers.

    Args:
        raw_query: Original caller query text.
        normalized_query: Case-folded single-space query text.

    Returns:
        Deterministic retrieval intent and bounded reason code.
    """
    tokens = _query_tokens(raw_query)
    if _DATE_TOKEN_PATTERN.search(raw_query) is not None and _is_title_like(
        raw_query, normalized_query, tokens
    ):
        return ContextRetrievalIntent.EXACT_OR_TITLE, "dated_title_like_query"
    ordered_rules = (
        (
            ContextRetrievalIntent.TEMPORAL_CURRENT_STATE,
            _TEMPORAL_MARKERS,
            "temporal_marker",
        ),
        (
            ContextRetrievalIntent.EXPERIENTIAL,
            _EXPERIENTIAL_MARKERS,
            "experiential_marker",
        ),
        (
            ContextRetrievalIntent.PROCEDURAL,
            _PROCEDURAL_MARKERS,
            "procedural_marker",
        ),
        (
            ContextRetrievalIntent.GRAPH_ORIENTED,
            _GRAPH_MARKERS,
            "graph_marker",
        ),
    )
    for intent, markers, reason in ordered_rules:
        if _contains_marker(normalized_query, markers):
            return intent, reason
    if _is_title_like(raw_query, normalized_query, tokens):
        return ContextRetrievalIntent.EXACT_OR_TITLE, "short_title_like_query"
    if "?" in raw_query or _contains_marker(normalized_query, _SEMANTIC_MARKERS):
        return ContextRetrievalIntent.SEMANTIC_PARAPHRASE, "semantic_question_marker"
    return ContextRetrievalIntent.MIXED, "mixed_query_fallback"


def _inferred_memory_functions(
    intent: ContextRetrievalIntent,
) -> tuple[MemoryFunction, ...]:
    """Return only high-confidence functional-memory preferences for v1.

    Args:
        intent: Deterministic adaptive retrieval intent.

    Returns:
        Inferred soft MemoryFunction preferences, if confidence is high.
    """
    if intent is ContextRetrievalIntent.EXPERIENTIAL:
        return (MemoryFunction.EXPERIENTIAL,)
    if intent is ContextRetrievalIntent.PROCEDURAL:
        return (MemoryFunction.PROCEDURAL,)
    return ()


def _normalized_query(query: str) -> str:
    """Return case-folded single-space query text for deterministic markers.

    Args:
        query: Raw caller query text.

    Returns:
        Normalized query text used only for deterministic classification.
    """
    return " ".join(query.casefold().split())


def _query_tokens(query: str) -> tuple[str, ...]:
    """Return stable alphanumeric/Korean query tokens.

    Args:
        query: Raw caller query text.

    Returns:
        Ordered token sequence used by the title-like heuristic.
    """
    return tuple(match.group(0) for match in _QUERY_TOKEN_PATTERN.finditer(query))


def _contains_marker(query: str, markers: tuple[str, ...]) -> bool:
    """Return whether normalized query contains one explicit v1 marker.

    Args:
        query: Normalized query text.
        markers: Explicit versioned marker phrases.

    Returns:
        Whether at least one marker occurs in the normalized query.
    """
    return any(marker in query for marker in markers)


def _is_title_like(
    raw_query: str,
    normalized_query: str,
    tokens: tuple[str, ...],
) -> bool:
    """Recognize bounded identifier/title-like lookups without semantic guessing.

    Args:
        raw_query: Original caller query text.
        normalized_query: Normalized query text.
        tokens: Deterministic query tokens.

    Returns:
        Whether the query is safe to treat as a lexical title-like lookup.
    """
    if not tokens:
        return False
    if any(character in raw_query for character in "?!。"):
        return False
    if _contains_marker(normalized_query, _SEMANTIC_MARKERS):
        return False
    if _DATE_TOKEN_PATTERN.search(raw_query) is not None:
        return True
    if len(tokens) > _TITLE_LIKE_MAX_TOKENS:
        return False
    return len(raw_query.strip()) <= _TITLE_LIKE_MAX_CHARACTERS


def _hybrid_budget(top_k: int) -> int:
    """Return the v1 budget aligned with the existing Rust hybrid over-fetch contract.

    Args:
        top_k: Requested final result count.

    Returns:
        Bounded per-lane candidate budget.
    """
    return min(_MAX_CANDIDATE_BUDGET, max(top_k, top_k * _HYBRID_CANDIDATE_MULTIPLIER))
