"""Shared text hashing and lightweight token counting helpers."""

from __future__ import annotations

import hashlib
import re
from typing import Final

_WORD_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\w+")


def sha256_text_hexdigest(text: str) -> str:
    """Return the SHA-256 hex digest for UTF-8 text content.

    Args:
        text: Text content to hash.

    Returns:
        SHA-256 hex digest for the UTF-8 encoded content.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_word_tokens(
    text: str,
    max_tokens: int | None = None,
    max_token_length: int | None = None,
) -> tuple[str, ...]:
    """Extract simple word-like tokens from text content.

    Args:
        text: Text content to scan.
        max_tokens: Optional maximum number of tokens to return.
        max_token_length: Optional maximum number of characters per token.

    Returns:
        Ordered word-like tokens found in the content.
    """
    tokens = _WORD_TOKEN_PATTERN.findall(text)
    if max_tokens is not None:
        tokens = tokens[:max_tokens]
    if max_token_length is not None:
        tokens = [token[:max_token_length] for token in tokens]
    return tuple(tokens)


def count_word_tokens(text: str) -> int:
    """Count simple word-like tokens in text content.

    Args:
        text: Text content to count.

    Returns:
        Number of ``\\w+`` tokens found in the content.
    """
    return len(extract_word_tokens(text))
