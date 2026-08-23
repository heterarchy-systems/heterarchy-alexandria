"""System-owned metadata policy for explicit canonical note writes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from app.obsidian.application.notes.obsidian_note_templates import frontmatter_for_save
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianFrontmatterMode
from app.obsidian.infrastructure.markdown.frontmatter import timestamp_text
from app.shared.compute.native_text_hashing import hash_text
from app.shared.types.extra_types import JSONObject

_IMMUTABLE_SYSTEM_FIELDS = frozenset(
    {
        "id",
        "created_at",
        "original_source",
        "initial_content_hash",
    }
)
_HISTORY_FIELDS = frozenset(
    {
        "updated_at",
        "version",
        "previous_content_hash",
        "content_hash",
    }
)


def frontmatter_for_explicit_write(
    payload: ObsidianSaveNote,
    note_id: str,
    title: str,
    existing: ObsidianNote | None,
    mode: ObsidianFrontmatterMode,
    redaction_warnings: list[str],
) -> JSONObject:
    """Merge caller fields while retaining server-owned identity and history.

    Args:
        payload: Value supplied to frontmatter_for_explicit_write.
        note_id: Value supplied to frontmatter_for_explicit_write.
        title: Value supplied to frontmatter_for_explicit_write.
        existing: Value supplied to frontmatter_for_explicit_write.
        mode: Value supplied to frontmatter_for_explicit_write.
        redaction_warnings: Value supplied to frontmatter_for_explicit_write.

    Returns:
        Result produced by frontmatter_for_explicit_write.
    """
    incoming = dict(payload.frontmatter)
    if existing is None:
        merged = incoming
    elif mode is ObsidianFrontmatterMode.MERGE:
        merged = {**existing.frontmatter, **incoming}
    else:
        merged = {
            key: value
            for key, value in existing.frontmatter.items()
            if key in _IMMUTABLE_SYSTEM_FIELDS | _HISTORY_FIELDS
        }
        merged.update(incoming)

    if existing is not None:
        for field in _IMMUTABLE_SYSTEM_FIELDS:
            if field in existing.frontmatter:
                merged[field] = existing.frontmatter[field]
        merged["created_at"] = existing.frontmatter.get(
            "created_at",
            timestamp_text(existing.modified_at),
        )
        merged["original_source"] = existing.frontmatter.get(
            "original_source",
            existing.source or payload.source,
        )
        merged["initial_content_hash"] = existing.frontmatter.get(
            "initial_content_hash",
            existing.frontmatter.get("content_hash", hash_text(existing.body)),
        )

    return frontmatter_for_save(
        replace(payload, frontmatter=merged),
        note_id=note_id,
        title=title,
        redaction_warnings=redaction_warnings,
    )


def write_is_unchanged(
    existing: ObsidianNote,
    desired_frontmatter: JSONObject,
    desired_body: str,
) -> bool:
    """Compare caller-visible canonical content without volatile history fields.

    Args:
        existing: Value supplied to write_is_unchanged.
        desired_frontmatter: Value supplied to write_is_unchanged.
        desired_body: Value supplied to write_is_unchanged.

    Returns:
        Result produced by write_is_unchanged.
    """
    indexed_body = "\n" + desired_body.rstrip("\n")
    return indexed_body == existing.body and _without_history(
        desired_frontmatter
    ) == _without_history(existing.frontmatter)


def apply_write_history(
    frontmatter: JSONObject,
    existing: ObsidianNote | None,
    body: str,
) -> JSONObject:
    """Apply protected timestamps, monotonic version, and body hash history.

    Args:
        frontmatter: Value supplied to apply_write_history.
        existing: Value supplied to apply_write_history.
        body: Value supplied to apply_write_history.

    Returns:
        Result produced by apply_write_history.
    """
    updated = dict(frontmatter)
    now = timestamp_text(datetime.now(UTC))
    body_hash = hash_text(body)
    if existing is None:
        updated["created_at"] = now
        updated["original_source"] = updated.get("source")
        updated["version"] = 1
        updated["initial_content_hash"] = body_hash
    else:
        updated["created_at"] = existing.frontmatter.get(
            "created_at",
            timestamp_text(existing.modified_at),
        )
        updated["original_source"] = existing.frontmatter.get(
            "original_source",
            existing.source or updated.get("source"),
        )
        updated["initial_content_hash"] = existing.frontmatter.get(
            "initial_content_hash",
            existing.frontmatter.get("content_hash", hash_text(existing.body)),
        )
        updated["previous_content_hash"] = existing.frontmatter.get(
            "content_hash",
            hash_text(existing.body),
        )
        updated["version"] = _version(existing.frontmatter.get("version")) + 1
    updated["updated_at"] = now
    updated["content_hash"] = body_hash
    updated["last_modified_by"] = updated.get("source") or "unknown"
    return updated


def _without_history(frontmatter: JSONObject) -> JSONObject:
    """Execute without history.

    Args:
        frontmatter: Frontmatter used by this operation.

    Returns:
        JSONObject result produced by without history.
    """
    return {
        key: value for key, value in frontmatter.items() if key not in _HISTORY_FIELDS
    }


# Broad type justified: parsed frontmatter scalars may have heterogeneous runtime types.
def _version(value: object) -> int:
    """Execute version.

    Args:
        value: Value being processed.

    Returns:
        int result produced by version.
    """
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return max(value, 1)
    if isinstance(value, str) and value.isdigit():
        return max(int(value), 1)
    return 1
