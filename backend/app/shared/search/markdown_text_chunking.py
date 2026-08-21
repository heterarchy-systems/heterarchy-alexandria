"""Bounded, overlapping Markdown text chunking for search indexes."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_SEARCH_CHUNK_MAX_CHARS = 1400
DEFAULT_SEARCH_CHUNK_OVERLAP_CHARS = 160
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


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
    """Split Markdown into deterministic heading-aware overlapping chunks.

    Args:
        title: Document title used as fallback heading.
        content: Markdown body.
        max_chars: Maximum characters in one returned chunk.
        overlap_chars: Target overlap carried across large-section boundaries.

    Returns:
        Ordered bounded search chunks.
    """
    normalized = content.strip() or title.strip()
    matches = list(HEADING_PATTERN.finditer(normalized))
    sections: list[tuple[str | None, str]] = []
    if not matches:
        sections.append((title, normalized))
    else:
        if matches[0].start() > 0:
            sections.append((title, normalized[: matches[0].start()].strip()))
        for index, match in enumerate(matches):
            start = match.start()
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(normalized)
            )
            sections.append((match.group(2).strip(), normalized[start:end].strip()))

    chunks: list[SearchTextChunk] = []
    for heading, section in sections:
        if not section:
            continue
        for part in _split_large_section(
            section,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        ):
            chunks.append(
                SearchTextChunk(
                    chunk_index=len(chunks),
                    heading=heading,
                    content=part,
                )
            )
    return chunks


def _split_large_section(
    section: str,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    if len(section) <= max_chars:
        return [section]
    chunks: list[str] = []
    start = 0
    while start < len(section):
        hard_end = min(start + max_chars, len(section))
        end = _preferred_chunk_end(section, start=start, hard_end=hard_end)
        chunk = section[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(section):
            break
        next_start = max(start + 1, end - overlap_chars)
        while (
            next_start < end
            and next_start > start
            and not section[next_start - 1].isspace()
        ):
            next_start += 1
        start = next_start
    return chunks


def _preferred_chunk_end(section: str, start: int, hard_end: int) -> int:
    if hard_end >= len(section):
        return len(section)
    minimum_end = start + ((hard_end - start) // 2)
    for separator in ("\n\n", "\n", ". ", " "):
        boundary = section.rfind(separator, minimum_end, hard_end)
        if boundary >= minimum_end:
            return boundary + (1 if separator == ". " else len(separator))
    return hard_end
