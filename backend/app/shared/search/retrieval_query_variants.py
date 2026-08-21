"""Focused lexical query variants for bounded retrieval fallback."""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Final

from app.shared.utils.text_metrics import extract_word_tokens

_QUERY_SEGMENT_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[,;\n.!?。]+")


def focused_query_variants(
    query: str,
    stop_tokens: Collection[str] = frozenset(),
    max_variants: int = 16,
) -> tuple[str, ...]:
    """Return broad-to-focused lexical variants for one natural-language query.

    Args:
        query: Raw natural-language query.
        stop_tokens: Case-insensitive whole tokens to omit from focused variants.
        max_variants: Maximum variants returned.

    Returns:
        De-duplicated query variants in deterministic priority order.
    """
    variants: list[str] = []
    _append_variant(variants, query)
    for segment in _QUERY_SEGMENT_SPLIT_RE.split(query):
        tokens = tuple(
            token
            for token in extract_word_tokens(segment)
            if len(token) > 1 and token.casefold() not in stop_tokens
        )
        _append_token_variant(variants, tokens)
        for window_size in (4, 3, 2):
            if len(tokens) <= window_size:
                continue
            _append_token_variant(variants, tokens[:window_size])
            _append_token_variant(variants, tokens[-window_size:])
            for start in range(1, len(tokens) - window_size):
                _append_token_variant(
                    variants,
                    tokens[start : start + window_size],
                )
                if len(variants) >= max_variants:
                    break
            if len(variants) >= max_variants:
                break
        if len(variants) >= max_variants:
            break
    return tuple(variants[:max_variants])


def _append_token_variant(variants: list[str], tokens: tuple[str, ...]) -> None:
    if tokens:
        _append_variant(variants, " ".join(tokens))


def _append_variant(variants: list[str], query: str) -> None:
    normalized = " ".join(query.split())
    if normalized and normalized not in variants:
        variants.append(normalized)
