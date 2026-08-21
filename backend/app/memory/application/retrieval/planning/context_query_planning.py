"""Query planning for Context FTS recall."""

from __future__ import annotations

from typing import Final

from app.shared.search.retrieval_query_variants import focused_query_variants

MAX_CONTEXT_QUERY_VARIANTS: Final[int] = 16
CONTEXT_QUERY_STOP_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "about",
        "find",
        "how",
        "please",
        "show",
        "what",
        "when",
        "where",
        "why",
        "관련",
        "뭐가",
        "무엇",
        "알려줘",
        "어떻게",
        "위해서",
        "있을까요",
        "찾아줘",
        "해주세요",
    }
)


def context_query_variants(query: str) -> tuple[str, ...]:
    """Return bounded broad-to-focused variants for Context lexical recall.

    Args:
        query: Raw Context recall query.

    Returns:
        Deterministic lexical query variants.
    """
    return focused_query_variants(
        query,
        stop_tokens=CONTEXT_QUERY_STOP_TOKENS,
        max_variants=MAX_CONTEXT_QUERY_VARIANTS,
    )
