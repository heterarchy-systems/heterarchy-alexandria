"""Bounded, overlapping Markdown text chunking for search indexes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

DEFAULT_SEARCH_CHUNK_MAX_CHARS = 1400
DEFAULT_SEARCH_CHUNK_OVERLAP_CHARS = 160


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchTextChunk:
    """One bounded Markdown chunk before index-specific enrichment."""

    chunk_index: int
    heading: str | None
    content: str


def split_markdown_text(
    title: str,
    content: str,
    max_chars: int = DEFAULT_SEARCH_CHUNK_MAX_CHARS,
    overlap_chars: int = DEFAULT_SEARCH_CHUNK_OVERLAP_CHARS,
) -> list[SearchTextChunk]:
    """Split Markdown through the Rust chunking authority.

    Args:
        title: Document title used as fallback heading.
        content: Markdown body.
        max_chars: Maximum characters in one returned chunk.
        overlap_chars: Target overlap carried across large-section boundaries.

    Returns:
        Ordered bounded search chunks mapped to the existing Python DTO.
    """
    # local import justified: avoids a public-API/native-adapter import cycle.
    from app.shared.search.native_markdown_text_chunking import (
        create_native_markdown_text_chunker,
    )

    return cast(
        list[SearchTextChunk],
        create_native_markdown_text_chunker().split(
            title=title,
            content=content,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        ),
    )
