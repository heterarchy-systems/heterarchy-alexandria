"""Stable metadata-aware document text for Context embeddings."""

from __future__ import annotations

EMBEDDING_DOCUMENT_INPUT_FORMAT = "context-title-heading-content-v1"


def build_embedding_document_text(
    content: str,
    title: str | None,
    heading: str | None,
) -> str:
    """Return deterministic embedding text with available document structure.

    Args:
        content: Canonical chunk content.
        title: Optional parent document title.
        heading: Optional chunk heading or heading path.

    Returns:
        Metadata-prefixed text used for document embedding.
    """
    metadata_lines: list[str] = []
    normalized_title = _normalized_optional_text(title)
    normalized_heading = _normalized_optional_text(heading)
    if normalized_title is not None:
        metadata_lines.append(f"Title: {normalized_title}")
    if normalized_heading is not None and normalized_heading != normalized_title:
        metadata_lines.append(f"Heading: {normalized_heading}")
    normalized_content = content.strip()
    if not metadata_lines:
        return normalized_content
    return "\n".join([*metadata_lines, "", normalized_content])


def _normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None
