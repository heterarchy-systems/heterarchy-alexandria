"""Authoritative Markdown reload helpers for Obsidian indexed notes."""

from __future__ import annotations

from pathlib import Path

from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.infrastructure.markdown.paths import resolve_note_path
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)


def authoritative_note_from_path(
    vault_path: Path,
    relative_path: str,
    alexandria_root: str,
    indexed: ObsidianNote,
) -> ObsidianNote:
    """Reload an indexed note from Markdown and preserve index status metadata.

    Args:
        vault_path: Absolute Obsidian vault root.
        relative_path: Vault-relative Markdown path.
        alexandria_root: Managed Alexandria folder inside the vault.
        indexed: Existing PostgreSQL index row used for index status metadata.

    Returns:
        Authoritative note body/frontmatter loaded from Markdown.
    """
    absolute = resolve_note_path(vault_path, relative_path)
    if not absolute.exists():
        raise ObsidianNotFoundError(f"Obsidian note not found: {relative_path}")
    payload = note_index_from_path(
        absolute,
        relative_path,
        alexandria_root=alexandria_root,
    )
    if payload is None:
        raise ObsidianValidationError(
            f"Obsidian note is missing Alexandria frontmatter: {relative_path}"
        )
    return ObsidianNote(
        note_id=payload.note_id,
        relative_path=payload.relative_path,
        alexandria_type=payload.alexandria_type,
        title=payload.title,
        status=payload.status,
        tags=tuple(payload.tags),
        project=payload.project,
        source=payload.source,
        content_hash=payload.content_hash,
        frontmatter=payload.frontmatter,
        body=payload.body,
        index_status=indexed.index_status,
        error_message=indexed.error_message,
        size_bytes=payload.size_bytes,
        modified_at=payload.modified_at,
        indexed_at=indexed.indexed_at,
    )
