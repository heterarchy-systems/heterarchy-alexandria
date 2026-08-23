"""Behavior tests for shared text metric helpers."""

from __future__ import annotations

from app.shared.utils.text_metrics import (
    count_word_tokens,
    extract_word_tokens,
)


def test_extract_word_tokens_returns_ordered_tokens_when_content_has_punctuation() -> (
    None
):
    """Word-like chunk metrics should ignore punctuation-only separators."""
    assert extract_word_tokens("alpha, beta-gamma!\n42") == (
        "alpha",
        "beta",
        "gamma",
        "42",
    )


def test_extract_word_tokens_limits_count_and_length_when_requested() -> None:
    """FTS callers should be able to cap token count and token length."""
    assert extract_word_tokens(
        "abcdef ghijkl mnopqr",
        max_tokens=2,
        max_token_length=3,
    ) == ("abc", "ghi")


def test_count_word_tokens_matches_extracted_token_count_when_text_is_mixed() -> None:
    """Token count should use the same word-like contract as extraction."""
    content = "alpha, beta-gamma!\n42"
    assert count_word_tokens(content) == len(extract_word_tokens(content))
