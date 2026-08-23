"""Canonical Markdown serializer for Obsidian-backed Memory Compacts."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_contracts import (
    ALEXANDRIA_MEMORY_COMPACT_TYPE,
    DEFAULT_MEMORY_COMPACT_SOURCE,
    DEFAULT_MEMORY_COMPACT_TAGS,
    FRONTMATTER_DELIMITER,
)
from app.shared.serialization.orjson_codec import dumps_json
from app.shared.types.extra_types import JSONValue
from app.shared.types.types_convert_utils import aware_utc_datetime

type CompactFrontmatterValue = str | bool | tuple[str, ...] | None


def serialize_compact(compact: MemoryCompact) -> str:
    """Serialize one Memory Compact entity into an Obsidian Markdown note.

    Args:
        compact: Memory Compact entity to write.

    Returns:
        Markdown note text with YAML frontmatter.
    """
    source_refs = [
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
        if (link := _obsidian_source_link(source_ref.detail_path)) is not None
    )
    frontmatter: dict[str, CompactFrontmatterValue] = {
        "alexandria_type": ALEXANDRIA_MEMORY_COMPACT_TYPE,
        "id": compact.id,
        "tags": DEFAULT_MEMORY_COMPACT_TAGS,
        "status": compact.status.value,
        "source": DEFAULT_MEMORY_COMPACT_SOURCE,
        "project": compact.project,
        "covered_from": _isoformat(compact.covered_from),
        "covered_to": _isoformat(compact.covered_to),
        "created_at": _isoformat(compact.created_at),
        "updated_at": _isoformat(compact.updated_at),
        "archived_at": _isoformat(compact.archived_at)
        if compact.archived_at is not None
        else None,
        "review_verdict": compact.review_verdict.value
        if compact.review_verdict is not None
        else None,
        "review_score": str(compact.review_score)
        if compact.review_score is not None
        else None,
        "review_max_score": str(compact.review_max_score)
        if compact.review_max_score is not None
        else None,
        "reviewed_at": _isoformat(compact.reviewed_at)
        if compact.reviewed_at is not None
        else None,
        "source_refs": dumps_json(cast(JSONValue, source_refs)).decode("utf-8"),
        "source_ref_links": source_ref_links,
    }
    lines = [FRONTMATTER_DELIMITER]
    for key, value in frontmatter.items():
        lines.extend(_yaml_property_lines(key, value))
    lines.append(FRONTMATTER_DELIMITER)
    body = compact.markdown_body.rstrip("\n")
    return "\n".join(lines) + f"\n{body}\n"


def _isoformat(value: datetime) -> str:
    """Execute isoformat.

    Args:
        value: Value being processed.

    Returns:
        str result produced by isoformat.
    """
    return aware_utc_datetime(value).isoformat().replace("+00:00", "Z")


def _yaml_scalar(value: CompactFrontmatterValue) -> str:
    """Execute yaml scalar.

    Args:
        value: Value being processed.

    Returns:
        str result produced by yaml scalar.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        raise TypeError("list properties must be rendered as block sequences")
    if value.startswith("[") and value.endswith("]"):
        return value
    return _quoted_yaml_string(value)


def _quoted_yaml_string(value: str) -> str:
    """Execute quoted yaml string.

    Args:
        value: Value being processed.

    Returns:
        str result produced by quoted yaml string.
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _yaml_property_lines(key: str, value: CompactFrontmatterValue) -> list[str]:
    """Execute yaml property lines.

    Args:
        key: Key used by this operation.
        value: Value being processed.

    Returns:
        list[str] result produced by yaml property lines.
    """
    if isinstance(value, tuple):
        if not value:
            return [f"{key}: []"]
        return [f"{key}:", *[f"  - {_quoted_yaml_string(item)}" for item in value]]
    return [f"{key}: {_yaml_scalar(value)}"]


def _obsidian_source_link(detail_path: str) -> str | None:
    """Execute obsidian source link.

    Args:
        detail_path: Detail path used by this operation.

    Returns:
        str | None result produced by obsidian source link.
    """
    normalized = detail_path.strip().lstrip("/")
    if not normalized.lower().endswith(".md") or "://" in normalized:
        return None
    return f"[[{normalized[:-3]}]]"
