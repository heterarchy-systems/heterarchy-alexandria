"""Frontmatter parser for Obsidian-backed Memory Compact notes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
    MemoryStewardReadinessWarningCode,
)
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_contracts import (
    ALEXANDRIA_MEMORY_COMPACT_TYPE,
    FRONTMATTER_DELIMITER,
    UPDATED_AT_KEYS,
    CompactFrontmatterValue,
)
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.serialization.orjson_codec import loads_json
from app.shared.types.extra_types import JSONValue
from app.shared.types.types_convert_utils import aware_utc_datetime

type MutableCompactFrontmatterValue = str | bool | list[str] | None


def read_compact_file(path: Path) -> MemoryCompact | None:
    """Read one Obsidian note when it is an Alexandria Memory Compact.

    Args:
        path: Markdown note path.

    Returns:
        Memory Compact entity when the note is readable UTF-8 and has the
        expected frontmatter, otherwise None.
    """
    try:
        frontmatter, body = _FrontmatterSectionExtractor.read_frontmatter(
            path.read_text(encoding="utf-8")
        )
    except OSError, UnicodeDecodeError:
        return None
    if frontmatter.get("alexandria_type") != ALEXANDRIA_MEMORY_COMPACT_TYPE:
        return None
    return _TemporalMetadataParser.compact_from_frontmatter(frontmatter, body)


class _FrontmatterSectionExtractor:
    """Extract and coerce raw YAML frontmatter scalars and collections."""

    @staticmethod
    def read_frontmatter(text: str) -> tuple[dict[str, CompactFrontmatterValue], str]:
        """Split raw Markdown text into parsed frontmatter key-values and body text.

        Args:
            text: Raw Markdown document text.

        Returns:
            Tuple of parsed frontmatter mapping and Markdown body text.
        """
        raw_lines = text.split("\n")
        if not raw_lines or raw_lines[0].strip() != FRONTMATTER_DELIMITER:
            return {}, text
        try:
            end_index = next(
                index
                for index, line in enumerate(raw_lines[1:], start=1)
                if line.strip() == FRONTMATTER_DELIMITER
            )
        except StopIteration:
            return {}, text
        mutable_frontmatter: dict[str, MutableCompactFrontmatterValue] = {}
        active_list_key: str | None = None
        for raw_line in raw_lines[1:end_index]:
            line = raw_line.rstrip("\r")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if active_list_key is not None and stripped.startswith("-"):
                current = mutable_frontmatter.get(active_list_key)
                if isinstance(current, list):
                    item = _FrontmatterSectionExtractor.parse_yaml_scalar(
                        stripped.removeprefix("-").strip()
                    )
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
                mutable_frontmatter[key] = (
                    _FrontmatterSectionExtractor.parse_yaml_value(value)
                )
        frontmatter = {
            key: tuple(value) if isinstance(value, list) else value
            for key, value in mutable_frontmatter.items()
        }
        body = "\n".join(raw_lines[end_index + 1 :])
        return frontmatter, body

    @staticmethod
    def parse_yaml_value(value: str) -> MutableCompactFrontmatterValue:
        """Parse an inline YAML collection or scalar frontmatter value.

        Args:
            value: Trimmed raw YAML property value.

        Returns:
            Parsed list of string items or scalar YAML value.
        """
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                return []
            if not inner.startswith(("{", "[")):
                return [
                    item
                    for raw_item in inner.split(",")
                    if isinstance(
                        item := _FrontmatterSectionExtractor.parse_yaml_scalar(
                            raw_item.strip()
                        ),
                        str,
                    )
                    and item
                ]
        return _FrontmatterSectionExtractor.parse_yaml_scalar(value)

    @staticmethod
    def parse_yaml_scalar(value: str) -> str | bool | None:
        """Parse a single YAML scalar token into a typed Python primitive.

        Args:
            value: Raw YAML scalar token.

        Returns:
            Unquoted string, boolean, or None for YAML null tokens.
        """
        if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
            return value[1:-1].replace("''", "'")
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            return value[1:-1]
        if value in {"", "null", "Null", "NULL", "~"}:
            return None
        if value in {"true", "True", "TRUE"}:
            return True
        if value in {"false", "False", "FALSE"}:
            return False
        return value

    @staticmethod
    def required_text(frontmatter: dict[str, CompactFrontmatterValue], key: str) -> str:
        """Read a required non-empty string property from parsed frontmatter.

        Args:
            frontmatter: Parsed frontmatter key-value mapping.
            key: Required frontmatter property key.

        Returns:
            Non-empty string value stored under the requested key.

        Raises:
            KeyError: When the key is absent from the frontmatter mapping.
            ValueError: When the stored value is not a non-empty string.
        """
        value = frontmatter[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"Missing Memory Compact frontmatter: {key}")
        return value

    @staticmethod
    def frontmatter_text(
        frontmatter: dict[str, CompactFrontmatterValue], key: str
    ) -> str | None:
        """Read an optional string property from parsed frontmatter.

        Args:
            frontmatter: Parsed frontmatter key-value mapping.
            key: Frontmatter property key to inspect.

        Returns:
            String value when present and typed as a string, otherwise None.
        """
        value = frontmatter.get(key)
        return value if isinstance(value, str) else None

    @staticmethod
    def optional_int(value: str | None) -> int | None:
        """Parse an optional decimal integer string from frontmatter metadata.

        Args:
            value: Optional decimal integer text.

        Returns:
            Parsed integer when non-empty text is provided, otherwise None.
        """
        if not value:
            return None
        return int(value)


class _SourceRefDecoder:
    """Decode Memory Compact source references from frontmatter values."""

    @staticmethod
    def from_frontmatter(
        value: CompactFrontmatterValue, compact_id: str
    ) -> tuple[MemoryCompactSourceRef, ...]:
        """Decode source references from a JSON string or legacy YAML string list.

        Args:
            value: Raw frontmatter value for ``source_refs``.
            compact_id: Fallback Memory Compact identifier for decoded references.

        Returns:
            Tuple of decoded MemoryCompactSourceRef entities.
        """
        if isinstance(value, str):
            return _SourceRefDecoder.from_json(value, compact_id=compact_id)
        if not isinstance(value, tuple):
            return ()
        refs: list[MemoryCompactSourceRef] = []
        for item in value:
            normalized = item.strip()
            if not normalized:
                continue
            serialized = normalized if normalized.startswith("[") else f"[{normalized}]"
            refs.extend(_SourceRefDecoder.from_json(serialized, compact_id=compact_id))
        return tuple(refs)

    @staticmethod
    def from_json(
        value: str | None, compact_id: str
    ) -> tuple[MemoryCompactSourceRef, ...]:
        """Decode a serialized JSON array of source reference objects.

        Args:
            value: Serialized JSON array string or None.
            compact_id: Fallback Memory Compact identifier for decoded references.

        Returns:
            Tuple of decoded MemoryCompactSourceRef entities.
        """
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
            refs.append(
                MemoryCompactSourceRef(
                    id=str(item.get("id") or new_uuid()),
                    compact_id=str(item.get("compact_id") or compact_id),
                    source_type=str(item.get("source_type") or ""),
                    source_id=str(item.get("source_id") or ""),
                    title=str(item.get("title") or ""),
                    detail_path=str(item.get("detail_path") or ""),
                    source_hash=_SourceRefDecoder.optional_string(
                        item.get("source_hash")
                    ),
                )
            )
        return tuple(refs)

    @staticmethod
    def optional_string(value: JSONValue | None) -> str | None:
        """Normalize a JSON value into an optional non-blank string.

        Args:
            value: Decoded JSON field value.

        Returns:
            Stripped non-empty string when present, otherwise None.
        """
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None


class _TemporalMetadataParser:
    """Assemble MemoryCompact entities and temporal/status metadata fields."""

    @staticmethod
    def compact_from_frontmatter(
        frontmatter: dict[str, CompactFrontmatterValue], body: str
    ) -> MemoryCompact | None:
        """Construct a MemoryCompact entity from parsed frontmatter and body text.

        Args:
            frontmatter: Parsed frontmatter key-value mapping.
            body: Markdown body text following the frontmatter fence.

        Returns:
            Constructed MemoryCompact entity, or None when required fields are invalid.
        """
        try:
            compact_id = _FrontmatterSectionExtractor.required_text(frontmatter, "id")
            status = _TemporalMetadataParser.status_from_frontmatter(frontmatter)
            created_at = _TemporalMetadataParser.datetime_from_frontmatter(
                frontmatter, ("created_at", "created", "date")
            )
            updated_at_missing = not any(
                isinstance(v := frontmatter.get(key), str) and bool(v.strip())
                for key in UPDATED_AT_KEYS
            )
            updated_at = _TemporalMetadataParser.datetime_from_frontmatter(
                frontmatter, UPDATED_AT_KEYS, fallback=created_at
            )
            covered_from = _TemporalMetadataParser.datetime_from_frontmatter(
                frontmatter, ("covered_from",), fallback=created_at
            )
            covered_to = _TemporalMetadataParser.datetime_from_frontmatter(
                frontmatter, ("covered_to",), fallback=updated_at
            )
            return MemoryCompact(
                id=compact_id,
                project=_FrontmatterSectionExtractor.frontmatter_text(
                    frontmatter, "project"
                ),
                covered_from=covered_from,
                covered_to=covered_to,
                markdown_body=body.rstrip("\n"),
                status=status,
                source_refs=_SourceRefDecoder.from_frontmatter(
                    frontmatter.get("source_refs"), compact_id=compact_id
                ),
                created_at=created_at,
                updated_at=updated_at,
                archived_at=_TemporalMetadataParser.optional_datetime(
                    _FrontmatterSectionExtractor.frontmatter_text(
                        frontmatter, "archived_at"
                    )
                ),
                review_verdict=_TemporalMetadataParser.optional_review_verdict(
                    _FrontmatterSectionExtractor.frontmatter_text(
                        frontmatter, "review_verdict"
                    )
                ),
                reviewed_body_hash=_FrontmatterSectionExtractor.frontmatter_text(
                    frontmatter, "reviewed_body_hash"
                ),
                review_receipt_hash=_FrontmatterSectionExtractor.frontmatter_text(
                    frontmatter, "review_receipt_hash"
                ),
                review_score=_FrontmatterSectionExtractor.optional_int(
                    _FrontmatterSectionExtractor.frontmatter_text(
                        frontmatter, "review_score"
                    )
                ),
                review_max_score=_FrontmatterSectionExtractor.optional_int(
                    _FrontmatterSectionExtractor.frontmatter_text(
                        frontmatter, "review_max_score"
                    )
                ),
                reviewed_at=_TemporalMetadataParser.optional_datetime(
                    _FrontmatterSectionExtractor.frontmatter_text(
                        frontmatter, "reviewed_at"
                    )
                ),
                source_set_hash=_FrontmatterSectionExtractor.frontmatter_text(
                    frontmatter, "source_set_hash"
                ),
                compaction_policy_version=_FrontmatterSectionExtractor.frontmatter_text(
                    frontmatter, "compaction_policy_version"
                ),
                generation_revision=_FrontmatterSectionExtractor.optional_int(
                    _FrontmatterSectionExtractor.frontmatter_text(
                        frontmatter, "generation_revision"
                    )
                ),
                generated_at=_TemporalMetadataParser.optional_datetime(
                    _FrontmatterSectionExtractor.frontmatter_text(
                        frontmatter, "generated_at"
                    )
                ),
                metadata_warnings=(
                    (
                        MemoryStewardReadinessWarningCode.MEMORY_COMPACT_TIMESTAMP_MISSING.value,
                    )
                    if updated_at_missing
                    else ()
                ),
            )
        except KeyError, TypeError, ValueError:
            return None

    @staticmethod
    def status_from_frontmatter(
        frontmatter: dict[str, CompactFrontmatterValue],
    ) -> MemoryCompactStatus:
        """Resolve the lifecycle status enum from parsed frontmatter.

        Args:
            frontmatter: Parsed frontmatter key-value mapping.

        Returns:
            Validated MemoryCompactStatus enum member.
        """
        value = _FrontmatterSectionExtractor.required_text(frontmatter, "status")
        return MemoryCompactStatus(value.strip().upper())

    @staticmethod
    def datetime_from_frontmatter(
        frontmatter: dict[str, CompactFrontmatterValue],
        keys: tuple[str, ...],
        fallback: datetime | None = None,
    ) -> datetime:
        """Resolve the first ISO-8601 timestamp found across candidate keys.

        Args:
            frontmatter: Parsed frontmatter key-value mapping.
            keys: Ordered candidate frontmatter keys to inspect.
            fallback: Optional fallback timestamp when no key is populated.

        Returns:
            Timezone-aware UTC datetime.

        Raises:
            ValueError: When no candidate key is populated and no fallback is given.
        """
        for key in keys:
            value = frontmatter.get(key)
            if isinstance(value, str) and value.strip():
                return _TemporalMetadataParser.parse_datetime(value)
        if fallback is not None:
            return fallback
        joined_keys = ", ".join(keys)
        raise ValueError(f"Missing Memory Compact frontmatter: {joined_keys}")

    @staticmethod
    def optional_datetime(value: str | None) -> datetime | None:
        """Parse an optional ISO-8601 timestamp string into a UTC datetime.

        Args:
            value: Optional ISO-8601 timestamp string.

        Returns:
            Timezone-aware UTC datetime when present, otherwise None.
        """
        if not value:
            return None
        return _TemporalMetadataParser.parse_datetime(value)

    @staticmethod
    def optional_review_verdict(
        value: str | None,
    ) -> MemoryCompactReviewVerdict | None:
        """Parse an optional review verdict string into its domain enum.

        Args:
            value: Optional review verdict string from frontmatter.

        Returns:
            Validated MemoryCompactReviewVerdict when present, otherwise None.
        """
        if not value:
            return None
        return MemoryCompactReviewVerdict(value)

    @staticmethod
    def parse_datetime(value: str) -> datetime:
        """Parse an ISO-8601 timestamp string and normalize to UTC.

        Args:
            value: ISO-8601 timestamp string.

        Returns:
            Timezone-aware UTC datetime.
        """
        return aware_utc_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
