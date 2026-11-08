"""One owner for atomic Markdown persistence and index-error evidence."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import TypedDict

import anyio
import anyio.to_thread

from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    authoritative_note_from_path_async,
    source_matches_hash,
)
from app.obsidian.application.notes.obsidian_note_indexer import (
    _read_source_text,
    note_index_from_path,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianNote,
    ObsidianNoteIndex,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianIndexStatus,
)
from app.obsidian.domain.repositories.obsidian_index_error_repository import (
    IObsidianIndexErrorRepository,
)
from app.obsidian.infrastructure.markdown.atomic_markdown_write import (
    atomic_write_markdown,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)

logger = logging.getLogger(__name__)


class IndexErrorLogExtra(TypedDict):
    """Safe, bounded fields attached to an index-error log entry."""

    note_path: str
    index_error_code: str


def persist_and_index(
    absolute: Path,
    document: str,
    safe_path: str,
    alexandria_root: str,
    *,
    expected_source_hash: str | None = None,
) -> ObsidianNoteIndex | None:
    """Persist source and parse its native index payload in one worker.

    Args:
        absolute: Resolved canonical Markdown path.
        document: Complete Markdown content to persist.
        safe_path: Validated Vault-relative path.
        alexandria_root: Managed note root in the Vault.
        expected_source_hash: Optional source CAS value.

    Returns:
        Parsed index payload, or None for unmanaged Markdown.

    Raises:
        ObsidianWriteConflictError: The source no longer matches the CAS value.
    """
    if expected_source_hash is not None:
        current_hash = hash_text(
            _read_source_text(path=absolute, max_source_bytes=None)
        )
        if current_hash != expected_source_hash:
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: source changed before repair persistence",
                current_content_hash=current_hash,
            )
    atomic_write_markdown(path=absolute, content=document)
    return note_index_from_path(
        path=absolute,
        relative_path=safe_path,
        alexandria_root=alexandria_root,
    )


async def record_index_error_best_effort(
    index_error: ObsidianIndexError,
    repository: IObsidianIndexErrorRepository,
) -> None:
    """Persist diagnostics without replacing the canonical write failure.

    Args:
        index_error: Source/index failure to record.
        repository: Existing PostgreSQL error-record writer.

    Returns:
        None. Repository errors remain best-effort, as on the original service.
    """
    try:
        await repository.record_index_error(index_error)
    except Exception:
        logger.exception(
            "failed to persist Obsidian index error",
            extra=IndexErrorLogExtra(
                note_path=index_error.note_path,
                index_error_code=index_error.error_code.value,
            ),
        )


async def validate_expected_source_state(
    payload: ObsidianSaveNote,
    indexed_note: ObsidianNote | None,
    safe_path: str,
    vault_path: Path,
    alexandria_root: str,
) -> None:
    """Reject CAS writes when Markdown drifted from the PostgreSQL projection.

    When the indexed raw-source hash still matches, the caller may proceed. A
    mismatch is resolved through the authoritative Markdown parser because
    Context ``content_hash`` covers its logical body rather than raw source.

    Args:
        payload: Validated write request with its optional compare-and-swap hash.
        indexed_note: Current rebuildable PostgreSQL index row for this path.
        safe_path: Validated Vault-relative Markdown path.
        vault_path: Vault root captured at the operation boundary.
        alexandria_root: Managed root captured with the same Vault configuration.

    Raises:
        ObsidianWriteConflictError: The canonical source cannot be proven current.
    """
    if payload.expected_content_hash is None or indexed_note is None:
        return
    if indexed_note.source_hash is not None and await anyio.to_thread.run_sync(
        func=partial(
            source_matches_hash,
            vault_path=vault_path,
            relative_path=safe_path,
            alexandria_root=alexandria_root,
            source_hash=indexed_note.source_hash,
            max_source_bytes=indexed_note.size_bytes,
        ),
        limiter=anyio.to_thread.current_default_thread_limiter(),
    ):
        return
    try:
        current = await authoritative_note_from_path_async(
            vault_path=vault_path,
            relative_path=safe_path,
            alexandria_root=alexandria_root,
            indexed=indexed_note,
            expected_note_id=indexed_note.note_id,
        )
    except (OSError, ValueError, ObsidianNotFoundError, ObsidianValidationError) as exc:
        raise ObsidianWriteConflictError(
            "OBSIDIAN_WRITE_CONFLICT: canonical Markdown cannot be verified "
            f"before compare-and-swap: {safe_path}"
        ) from exc
    if current.index_status is ObsidianIndexStatus.STALE:
        raise ObsidianWriteConflictError(
            "OBSIDIAN_WRITE_CONFLICT: canonical Markdown changed since the "
            f"indexed compare-and-swap token was observed: {safe_path}"
        )


def restore_source_if_owned(
    absolute: Path,
    expected_document: str,
    previous_document: str,
) -> None:
    """Restore a failed repair only when its candidate still owns the current bytes.

    Args:
        absolute: Canonical Markdown path guarded by the mutation coordinator.
        expected_document: Candidate source published by this repair.
        previous_document: Original source captured before the repair.

    Raises:
        ObsidianWriteConflictError: Source changed or cannot be verified for rollback.
    """
    try:
        current = _read_source_text(absolute, max_source_bytes=None)
    except (OSError, UnicodeError) as exc:
        raise ObsidianWriteConflictError(
            "OBSIDIAN_WRITE_CONFLICT: source cannot be verified before repair rollback"
        ) from exc
    if current == previous_document:
        return
    if current != expected_document:
        raise ObsidianWriteConflictError(
            "OBSIDIAN_WRITE_CONFLICT: source changed before repair rollback",
            current_content_hash=hash_text(current),
        )
    atomic_write_markdown(path=absolute, content=previous_document)
