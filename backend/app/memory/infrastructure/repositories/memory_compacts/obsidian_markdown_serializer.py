"""Canonical Markdown serializer for Obsidian-backed Memory Compacts."""

from __future__ import annotations

from datetime import datetime

from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_contracts import (
    ALEXANDRIA_MEMORY_COMPACT_TYPE,
    DEFAULT_MEMORY_COMPACT_SOURCE,
    DEFAULT_MEMORY_COMPACT_TAGS,
    FRONTMATTER_DELIMITER,
    CompactFrontmatterValue,
)
from app.shared.serialization.orjson_codec import dumps_json
from app.shared.types.extra_types import JSONValue
from app.shared.types.types_convert_utils import aware_utc_datetime


def serialize_compact(compact: MemoryCompact) -> str:
    """Serialize one Memory Compact entity into an Obsidian Markdown note.

    Args:
        compact: Memory Compact entity to write.

    Returns:
        Markdown note text with YAML frontmatter.
    """
    source_refs: list[JSONValue] = [
        {
            "id": source_ref.id,
            "compact_id": source_ref.compact_id,
            "source_type": source_ref.source_type,
            "source_id": source_ref.source_id,
            "title": source_ref.title,
            "detail_path": source_ref.detail_path,
            "source_hash": source_ref.source_hash,
        }
        for source_ref in compact.source_refs
    ]
    source_ref_links = tuple(
        link
        for source_ref in compact.source_refs
        if (
            link := _CompactMarkdownFormatter.obsidian_source_link(
                source_ref.detail_path
            )
        )
        is not None
    )
    frontmatter: dict[str, CompactFrontmatterValue] = {
        "alexandria_type": ALEXANDRIA_MEMORY_COMPACT_TYPE,
        "id": compact.id,
        "tags": DEFAULT_MEMORY_COMPACT_TAGS,
        "status": compact.status.value,
        "source": DEFAULT_MEMORY_COMPACT_SOURCE,
        "project": compact.project,
        "covered_from": _CompactMarkdownFormatter.isoformat(compact.covered_from),
        "covered_to": _CompactMarkdownFormatter.isoformat(compact.covered_to),
        "created_at": _CompactMarkdownFormatter.isoformat(compact.created_at),
        "updated_at": _CompactMarkdownFormatter.isoformat(compact.updated_at),
        "archived_at": _CompactMarkdownFormatter.isoformat(compact.archived_at)
        if compact.archived_at is not None
        else None,
        "review_verdict": compact.review_verdict.value
        if compact.review_verdict is not None
        else None,
        "reviewed_body_hash": compact.reviewed_body_hash,
        "review_receipt_hash": compact.review_receipt_hash,
        "review_score": str(compact.review_score)
        if compact.review_score is not None
        else None,
        "review_max_score": str(compact.review_max_score)
        if compact.review_max_score is not None
        else None,
        "reviewed_at": _CompactMarkdownFormatter.isoformat(compact.reviewed_at)
        if compact.reviewed_at is not None
        else None,
        "source_set_hash": compact.source_set_hash,
        "compaction_policy_version": compact.compaction_policy_version,
        "generation_revision": str(compact.generation_revision)
        if compact.generation_revision is not None
        else None,
        "generated_at": _CompactMarkdownFormatter.isoformat(compact.generated_at)
        if compact.generated_at is not None
        else None,
        "source_refs": dumps_json(source_refs).decode("utf-8"),
        "source_ref_links": source_ref_links,
    }
    lines = [FRONTMATTER_DELIMITER]
    for key, value in frontmatter.items():
        lines.extend(_CompactMarkdownFormatter.yaml_property_lines(key, value))
    lines.append(FRONTMATTER_DELIMITER)
    body = compact.markdown_body.rstrip("\n")
    return "\n".join(lines) + f"\n{body}\n"


class _CompactMarkdownFormatter:
    """Format YAML frontmatter scalars, block sequences, and wikilink references."""

    @staticmethod
    def isoformat(value: datetime) -> str:
        """Format a datetime as a canonical UTC ISO-8601 string with a ``Z`` suffix.

        Args:
            value: Datetime to format.

        Returns:
            UTC ISO-8601 timestamp string ending in ``Z``.
        """
        return aware_utc_datetime(value).isoformat().replace("+00:00", "Z")

    @staticmethod
    def yaml_scalar(value: CompactFrontmatterValue) -> str:
        """Render a scalar frontmatter value as a YAML token.

        Args:
            value: Scalar frontmatter value to render.

        Returns:
            Rendered YAML scalar token string.

        Raises:
            TypeError: When a tuple collection is passed instead of a scalar value.
        """
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, tuple):
            raise TypeError("list properties must be rendered as block sequences")
        return _CompactMarkdownFormatter.quoted_yaml_string(value)

    @staticmethod
    def quoted_yaml_string(value: str) -> str:
        """Wrap a string in single quotes with YAML single-quote escaping.

        Args:
            value: Raw string value to quote.

        Returns:
            Single-quoted YAML string literal.
        """
        escaped = value.replace("'", "''")
        return f"'{escaped}'"

    @staticmethod
    def yaml_property_lines(key: str, value: CompactFrontmatterValue) -> list[str]:
        """Render one frontmatter key-value pair as one or more YAML lines.

        Args:
            key: YAML frontmatter property name.
            value: Scalar or tuple collection property value.

        Returns:
            Ordered YAML frontmatter lines for the property.
        """
        if isinstance(value, tuple):
            if not value:
                return [f"{key}: []"]
            return [
                f"{key}:",
                *[
                    f"  - {_CompactMarkdownFormatter.quoted_yaml_string(item)}"
                    for item in value
                ],
            ]
        if key == "source_refs" and isinstance(value, str):
            return [f"{key}: {value}"]
        return [f"{key}: {_CompactMarkdownFormatter.yaml_scalar(value)}"]

    @staticmethod
    def obsidian_source_link(detail_path: str) -> str | None:
        """Convert a vault-relative Markdown detail path into an Obsidian wikilink.

        Args:
            detail_path: Source reference detail path.

        Returns:
            Obsidian wikilink string when ``detail_path`` targets a vault Markdown note,
            otherwise None.
        """
        normalized = detail_path.strip().lstrip("/")
        if not normalized.lower().endswith(".md") or "://" in normalized:
            return None
        return f"[[{normalized[:-3]}]]"
