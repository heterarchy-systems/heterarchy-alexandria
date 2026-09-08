"""Authoritative Markdown reload helpers for Obsidian indexed notes."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import anyio

from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexStatus
from app.obsidian.infrastructure.markdown.paths import (
    safe_relative_path,
    validate_discovered_note_path,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)


def authoritative_note_from_path(
    vault_path: Path,
    relative_path: str,
    alexandria_root: str,
    indexed: ObsidianNote | None = None,
    *,
    expected_note_id: str | None = None,
    index_error: str | None = None,
) -> ObsidianNote:
    """Reload one managed note from canonical Markdown.

    Args:
        vault_path: Absolute Obsidian vault root.
        relative_path: Vault-relative Markdown path.
        alexandria_root: Managed Alexandria folder inside the vault.
        indexed: Optional PostgreSQL index row used for projection metadata.
        expected_note_id: Optional stable id that source frontmatter must match.
        index_error: Optional diagnostic explaining unavailable index metadata.

    Returns:
        Authoritative note body/frontmatter loaded from Markdown.
    """
    safe_path = _validated_source_path(
        vault_path=vault_path,
        relative_path=relative_path,
        alexandria_root=alexandria_root,
    )
    absolute = safe_path
    if not absolute.exists():
        raise ObsidianNotFoundError(f"Obsidian note not found: {relative_path}")
    try:
        payload = note_index_from_path(
            absolute,
            relative_path,
            alexandria_root=alexandria_root,
        )
    except (OSError, UnicodeError) as exc:
        raise ObsidianValidationError("SOURCE_READ_FAILED") from exc
    except ValueError as exc:
        raise ObsidianValidationError(_source_parse_error_code(exc)) from exc
    if payload is None:
        raise ObsidianValidationError(
            f"Obsidian note is missing Alexandria frontmatter: {relative_path}"
        )
    return authoritative_note_from_index(
        payload,
        indexed=indexed,
        expected_note_id=expected_note_id,
        index_error=index_error,
    )


async def authoritative_note_from_path_async(
    vault_path: Path,
    relative_path: str,
    alexandria_root: str,
    indexed: ObsidianNote | None = None,
    *,
    expected_note_id: str | None = None,
    index_error: str | None = None,
) -> ObsidianNote:
    """Reload canonical Markdown through the bounded framework thread lane."""
    loader = partial(
        authoritative_note_from_path,
        vault_path,
        relative_path,
        alexandria_root,
        indexed,
        expected_note_id=expected_note_id,
        index_error=index_error,
    )
    return await anyio.to_thread.run_sync(
        loader,
        limiter=anyio.to_thread.current_default_thread_limiter(),
    )


def authoritative_note_from_index(
    payload: ObsidianNoteIndex,
    *,
    indexed: ObsidianNote | None = None,
    expected_note_id: str | None = None,
    index_error: str | None = None,
) -> ObsidianNote:
    """Map one already-parsed source payload into a truthful read model.

    The payload is produced by the canonical Markdown parser. No persisted index
    body or metadata is used as a source fallback.
    """
    if expected_note_id is not None and payload.note_id != expected_note_id:
        raise ObsidianValidationError(
            "SOURCE_ID_MISMATCH: canonical Markdown id does not match requested id"
        )
    index_status = (
        ObsidianIndexStatus.UNINDEXED if indexed is None else indexed.index_status
    )
    error_message = index_error
    indexed_at = None if indexed is None else indexed.indexed_at
    if indexed is not None and indexed.relative_path != payload.relative_path:
        index_status = ObsidianIndexStatus.STALE
        indexed_at = indexed.indexed_at
        error_message = "INDEX_PATH_STALE"
    elif indexed is not None and indexed.content_hash != payload.content_hash:
        index_status = ObsidianIndexStatus.STALE
        indexed_at = indexed.indexed_at
        error_message = "INDEX_CONTENT_STALE"
    elif indexed is not None and indexed.frontmatter != payload.frontmatter:
        index_status = ObsidianIndexStatus.STALE
        indexed_at = indexed.indexed_at
        error_message = "INDEX_METADATA_STALE"
    elif indexed is not None and index_error is None:
        error_message = indexed.error_message
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
        index_status=index_status,
        error_message=error_message,
        size_bytes=payload.size_bytes,
        modified_at=payload.modified_at,
        indexed_at=indexed_at,
    )


def _validated_source_path(
    vault_path: Path,
    relative_path: str,
    alexandria_root: str,
) -> Path:
    """Resolve and validate one source path without following a symlink alias."""
    vault = Path(vault_path).resolve()
    safe_path = safe_relative_path(relative_path)
    candidate = vault / safe_path
    managed_root = (vault / safe_relative_path(alexandria_root)).resolve()
    if managed_root != candidate and managed_root not in candidate.parents:
        raise ObsidianValidationError(
            "PATH_SECURITY_VIOLATION: note path is outside the managed root"
        )
    if not candidate.exists():
        return candidate
    return validate_discovered_note_path(vault, alexandria_root, candidate)


def _source_parse_error_code(error: ValueError) -> str:
    """Map parser failures to secret-free typed source error codes."""
    message = str(error)
    for code in (
        "FRONTMATTER_SECRET_DETECTED",
        "INVALID_CONTENT_HASH",
        "INVALID_CONTENT_INTEGRITY",
        "INVALID_SCOPE_IDENTITY",
        "INVALID_SUPERSEDE",
    ):
        if code in message:
            return code
    return "FRONTMATTER_PARSE_ERROR"
