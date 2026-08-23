"""Markdown chunking for Context Vault retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.shared.compute.native_text_hashing import hash_texts
from app.shared.search.markdown_text_chunking import split_markdown_text
from app.shared.utils.text_metrics import count_word_tokens


@dataclass(frozen=True, slots=True)
class MarkdownChunk:
    """One chunk produced from Markdown context content."""

    chunk_index: int
    heading: str | None
    content: str
    token_count: int
    content_hash: str
    metadata: ContextMetadataPayload


def chunk_markdown(
    title: str,
    content: str,
    max_chars: int = 1400,
) -> list[MarkdownChunk]:
    """Split Markdown content into deterministic retrieval chunks.

    Args:
        title: Context title used as fallback heading.
        content: Markdown or text body.
        max_chars: Soft maximum characters per chunk.

    Returns:
        Ordered chunks with hashes and token counts.
    """
    text_chunks = split_markdown_text(
        title=title,
        content=content,
        max_chars=max_chars,
    )
    content_hashes = hash_texts(tuple(chunk.content for chunk in text_chunks))
    return [
        MarkdownChunk(
            chunk_index=chunk.chunk_index,
            heading=chunk.heading,
            content=chunk.content,
            token_count=count_word_tokens(chunk.content),
            content_hash=content_hash,
            metadata={
                "title": title,
                "heading": chunk.heading or title,
            },
        )
        for chunk, content_hash in zip(text_chunks, content_hashes, strict=True)
    ]
