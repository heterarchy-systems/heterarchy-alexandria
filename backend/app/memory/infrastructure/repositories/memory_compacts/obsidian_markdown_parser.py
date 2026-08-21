"""Frontmatter parser for Obsidian-backed Memory Compact notes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast

from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
)
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_contracts import (
    ALEXANDRIA_MEMORY_COMPACT_TYPE,
    FRONTMATTER_DELIMITER,
    UPDATED_AT_KEYS,
)
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.serialization.orjson_codec import loads_json
from app.shared.types.extra_types import JSONObject, JSONValue
from app.shared.types.types_convert_utils import aware_utc_datetime

type CompactFrontmatterValue = str | bool | tuple[str, ...] | None
type MutableCompactFrontmatterValue = str | bool | list[str] | None


def read_compact_file(path: Path) -> MemoryCompact | None:
    """Read one Obsidian note when it is an Alexandria Memory Compact.

    Args:
        path: Markdown note path.

    Returns:
        Memory Compact entity when the note has the expected frontmatter.
    """
    try:
        frontmatter, body = _read_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    if frontmatter.get("alexandria_type") != ALEXANDRIA_MEMORY_COMPACT_TYPE:
        return None
    return _compact_from_frontmatter(frontmatter, body)


def _read_frontmatter(text: str) -> tuple[dict[str, CompactFrontmatterValue], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return {}, text
    try:
        end_index = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == FRONTMATTER_DELIMITER
        )
    except StopIteration:
        return {}, text
    mutable_frontmatter: dict[str, MutableCompactFrontmatterValue] = {}
    active_list_key: str | None = None
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if active_list_key is not None and stripped.startswith("-"):
            current = mutable_frontmatter.get(active_list_key)
            if isinstance(current, list):
                item = _parse_yaml_scalar(stripped.removeprefix("-").strip())
                if isinstance(item, str):
                    current.append(item)
            continue
        active_list_key = None
        if line != line.lstrip() or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            continue
        if value == "":
            mutable_frontmatter[key] = []
            active_list_key = key
        else:
            mutable_frontmatter[key] = _parse_yaml_value(value)
    frontmatter = {
        key: tuple(value) if isinstance(value, list) else value
        for key, value in mutable_frontmatter.items()
    }
    body = "\n".join(lines[end_index + 1 :])
    return frontmatter, body


def _compact_from_frontmatter(
    frontmatter: dict[str, CompactFrontmatterValue], body: str
) -> MemoryCompact | None:
    try:
        compact_id = _required_text(frontmatter, "id")
        status = _status_from_frontmatter(frontmatter)
        created_at = _datetime_from_frontmatter(
            frontmatter, ("created_at", "created", "date")
        )
        updated_at_missing = not any(frontmatter.get(key) for key in UPDATED_AT_KEYS)
        updated_at = _datetime_from_frontmatter(
            frontmatter, UPDATED_AT_KEYS, fallback=created_at
        )
        covered_from = _datetime_from_frontmatter(
            frontmatter, ("covered_from",), fallback=created_at
        )
        covered_to = _datetime_from_frontmatter(
            frontmatter, ("covered_to",), fallback=updated_at
        )
        return MemoryCompact(
            id=compact_id,
            project=_frontmatter_text(frontmatter, "project"),
            covered_from=covered_from,
            covered_to=covered_to,
            markdown_body=body.rstrip("\n"),
            status=status,
            source_refs=_source_refs_from_frontmatter(
                frontmatter.get("source_refs"), compact_id=compact_id
            ),
            created_at=created_at,
            updated_at=updated_at,
            archived_at=_optional_datetime(
                _frontmatter_text(frontmatter, "archived_at")
            ),
            review_verdict=_optional_review_verdict(
                _frontmatter_text(frontmatter, "review_verdict")
            ),
            review_score=_optional_int(_frontmatter_text(frontmatter, "review_score")),
            review_max_score=_optional_int(
                _frontmatter_text(frontmatter, "review_max_score")
            ),
            reviewed_at=_optional_datetime(
                _frontmatter_text(frontmatter, "reviewed_at")
            ),
            metadata_warnings=(
                ("memory_compact_timestamp_missing",) if updated_at_missing else ()
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _source_refs_from_frontmatter(
    value: CompactFrontmatterValue, compact_id: str
) -> tuple[MemoryCompactSourceRef, ...]:
    if isinstance(value, str):
        return _source_refs_from_json(value, compact_id=compact_id)
    if not isinstance(value, tuple):
        return ()
    refs: list[MemoryCompactSourceRef] = []
    for item in value:
        normalized = item.strip()
        if not normalized:
            continue
        serialized = normalized if normalized.startswith("[") else f"[{normalized}]"
        refs.extend(_source_refs_from_json(serialized, compact_id=compact_id))
    return tuple(refs)


def _source_refs_from_json(
    value: str | None, compact_id: str
) -> tuple[MemoryCompactSourceRef, ...]:
    if not value:
        return ()
    try:
        decoded = loads_json(value)
    except ValueError:
        return ()
    if not isinstance(decoded, list):
        return ()
    refs: list[MemoryCompactSourceRef] = []
    for item in decoded:
        if not isinstance(item, dict):
            continue
        payload = cast(JSONObject, item)
        refs.append(
            MemoryCompactSourceRef(
                id=str(payload.get("id") or new_uuid()),
                compact_id=str(payload.get("compact_id") or compact_id),
                source_type=str(payload.get("source_type") or ""),
                source_id=str(payload.get("source_id") or ""),
                title=str(payload.get("title") or ""),
                detail_path=str(payload.get("detail_path") or ""),
                source_hash=_optional_string(payload.get("source_hash")),
            )
        )
    return tuple(refs)


def _required_text(frontmatter: dict[str, CompactFrontmatterValue], key: str) -> str:
    value = frontmatter[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing Memory Compact frontmatter: {key}")
    return value


def _frontmatter_text(
    frontmatter: dict[str, CompactFrontmatterValue], key: str
) -> str | None:
    value = frontmatter.get(key)
    return value if isinstance(value, str) else None


def _optional_string(value: JSONValue | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _status_from_frontmatter(
    frontmatter: dict[str, CompactFrontmatterValue],
) -> MemoryCompactStatus:
    value = _required_text(frontmatter, "status")
    return MemoryCompactStatus(value.strip().upper())


def _datetime_from_frontmatter(
    frontmatter: dict[str, CompactFrontmatterValue],
    keys: tuple[str, ...],
    fallback: datetime | None = None,
) -> datetime:
    for key in keys:
        value = frontmatter.get(key)
        if isinstance(value, str) and value:
            return _parse_datetime(value)
    if fallback is not None:
        return fallback
    joined_keys = ", ".join(keys)
    raise ValueError(f"Missing Memory Compact frontmatter: {joined_keys}")


def _optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return _parse_datetime(value)


def _optional_review_verdict(value: str | None) -> MemoryCompactReviewVerdict | None:
    if not value:
        return None
    return MemoryCompactReviewVerdict(value)


def _optional_int(value: str | None) -> int | None:
    if not value:
        return None
    return int(value)


def _parse_datetime(value: str) -> datetime:
    return aware_utc_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _parse_yaml_value(value: str) -> MutableCompactFrontmatterValue:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        if not inner.startswith(("{", "[")):
            return [
                item
                for raw_item in inner.split(",")
                if isinstance(item := _parse_yaml_scalar(raw_item.strip()), str)
                and item
            ]
    return _parse_yaml_scalar(value)


def _parse_yaml_scalar(value: str) -> str | bool | None:
    if value in {"", "null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value
