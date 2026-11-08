"""Authoritative Markdown note reading and projection lookup."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial

import anyio
import anyio.to_thread
from sqlalchemy.exc import SQLAlchemyError

from app.obsidian.application.notes.frontmatter.obsidian_frontmatter_redaction import (
    frontmatter_contains_secret_field,
)
from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    _source_parse_error_code,
    authoritative_note_from_index,
    authoritative_note_from_path_async,
)
from app.obsidian.application.notes.obsidian_note_indexer import (
    _read_source_text,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianNoteRawRead,
    ObsidianVaultSourceSnapshot,
)
from app.obsidian.domain.repositories.obsidian_index_query_repository import (
    IObsidianIndexQueryRepository,
)
from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_json,
    parse_markdown_document,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
    safe_relative_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)
from app.shared.types.extra_types import JSONObject

SOURCE_METADATA_LOOKUP_TIMEOUT_SECONDS = 1.0
logger = logging.getLogger(__name__)
_RAW_READ_CODED_MESSAGE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*:")


@dataclass(frozen=True, slots=True)
class IndexMetadataLookup:
    """Bounded PostgreSQL lookup result for one source read."""

    note: ObsidianNote | None
    unavailable: bool


def _bounded_raw_read_error_message(message: str, mapped_code: str) -> str:
    """Bound a raw-read parse error to the parser's own coded diagnostics.

    Args:
        message: Raw parser exception message.
        mapped_code: Secret-free typed code mapped for this failure.

    Returns:
        The coded parser message, or the mapped code alone when uncoded.
    """
    if _RAW_READ_CODED_MESSAGE_PATTERN.match(message):
        return message
    return mapped_code


async def best_effort_index_lookup(
    lookup: Callable[[], Awaitable[ObsidianNote | None]],
) -> IndexMetadataLookup:
    """Read projection metadata without making it a source-read prerequisite.

    Args:
        lookup: One asynchronous repository projection lookup.

    Returns:
        The indexed note and whether the projection could not be read.
    """
    try:
        async with asyncio.timeout(SOURCE_METADATA_LOOKUP_TIMEOUT_SECONDS):
            return IndexMetadataLookup(note=await lookup(), unavailable=False)
    except SQLAlchemyError, OSError:
        logger.warning("Obsidian index metadata is unavailable during source read")
        return IndexMetadataLookup(note=None, unavailable=True)


class ObsidianNoteReader:
    """Read canonical Markdown while treating the PostgreSQL index as a projection."""

    def __init__(
        self,
        repository: IObsidianIndexQueryRepository,
        vault_config_store: ObsidianVaultConfigStore,
        source_snapshot: Callable[[int], Awaitable[ObsidianVaultSourceSnapshot]],
        source_scan_limit: int,
    ) -> None:
        """Create a reader with one source-snapshot owner.

        Args:
            repository: Bounded indexed projection reader.
            vault_config_store: Current authoritative Vault location.
            source_snapshot: One bounded source scan callback.
            source_scan_limit: Maximum files allowed in a fallback scan.
        """
        if source_scan_limit <= 0:
            raise ObsidianValidationError("source_scan_limit must be greater than zero")
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._source_snapshot = source_snapshot
        self._source_scan_limit = source_scan_limit

    async def read_note(self, note_id: str) -> ObsidianNote:
        """Read one managed note by stable id and reload its Markdown body.

        Args:
            note_id: Stable note id from frontmatter.

        Returns:
            Authoritative note loaded from Markdown.
        """
        config = self._vault_config_store.current()
        metadata = await best_effort_index_lookup(
            lambda: self._repository.get_by_id(note_id)
        )
        indexed = metadata.note
        metadata_unavailable = metadata.unavailable
        if indexed is None:
            return await self._read_note_from_source_snapshot(
                note_id=note_id,
                indexed=None,
                metadata_unavailable=metadata_unavailable,
            )
        try:
            return await authoritative_note_from_path_async(
                vault_path=config.vault_path,
                relative_path=indexed.relative_path,
                alexandria_root=config.alexandria_root,
                indexed=indexed,
                expected_note_id=note_id,
            )
        except ObsidianNotFoundError:
            return await self._read_note_from_source_snapshot(
                note_id=note_id,
                indexed=indexed,
                metadata_unavailable=False,
            )

    async def read_note_raw(
        self,
        *,
        path: str | None = None,
        note_id: str | None = None,
    ) -> ObsidianNoteRawRead:
        """Read one note's raw source even when its frontmatter fails to parse.

        This is the read-only operator surface for minimal repair: the raw
        text, its Rust content hash, and bounded parse diagnostics are
        returned without ever leaking secret-like frontmatter content.

        Args:
            path: Vault-relative Markdown path.
            note_id: Stable note id from frontmatter.

        Returns:
            Raw source read result with bounded, secret-free diagnostics.
        """
        if path is not None:
            safe_path = str(safe_relative_path(path))
        elif note_id is not None:
            indexed = await self._repository.get_by_id(note_id)
            if indexed is None:
                raise ObsidianNotFoundError(f"Obsidian note not found: {note_id}")
            safe_path = indexed.relative_path
        else:
            raise ObsidianValidationError("path or note_id is required")
        config = self._vault_config_store.current()
        absolute = resolve_note_path(config.vault_path, safe_path)
        if not absolute.exists():
            raise ObsidianNotFoundError(f"Obsidian note not found: {safe_path}")
        try:
            text = await anyio.to_thread.run_sync(
                partial(_read_source_text, absolute, max_source_bytes=None),
                limiter=anyio.to_thread.current_default_thread_limiter(),
            )
        except (OSError, UnicodeError) as exc:
            raise ObsidianValidationError("SOURCE_READ_FAILED") from exc
        indexed_metadata = await best_effort_index_lookup(
            lambda: self._repository.get_by_path(safe_path)
        )
        indexed_row = indexed_metadata.note
        if frontmatter_contains_secret_field(text):
            return ObsidianNoteRawRead(
                relative_path=safe_path,
                raw_text="",
                content_hash=None,
                byte_exact=False,
                byte_length=len(text.encode("utf-8")),
                parse_status="FRONTMATTER_SECRET_DETECTED",
                parse_error=None,
                frontmatter=None,
                body=None,
                note_id=None if indexed_row is None else indexed_row.note_id,
                index_status=(
                    None if indexed_row is None else indexed_row.index_status.value
                ),
            )
        content_hash = hash_text(text)
        frontmatter: JSONObject | None = None
        body: str | None = None
        parse_error: str | None = None
        try:
            document = parse_markdown_document(text)
        except ValueError as exc:
            parse_status = _source_parse_error_code(exc)
            parse_error = _bounded_raw_read_error_message(
                message=str(exc), mapped_code=parse_status
            )
        else:
            parse_status = "OK"
            frontmatter = frontmatter_json(document.frontmatter)
            body = document.body
        return ObsidianNoteRawRead(
            relative_path=safe_path,
            raw_text=text,
            content_hash=content_hash,
            byte_exact=True,
            byte_length=len(text.encode("utf-8")),
            parse_status=parse_status,
            parse_error=parse_error,
            frontmatter=frontmatter,
            body=body,
            note_id=None if indexed_row is None else indexed_row.note_id,
            index_status=(
                None if indexed_row is None else indexed_row.index_status.value
            ),
        )

    async def read_note_by_path(self, relative_path: str) -> ObsidianNote:
        """Read one managed note by vault-relative path.

        Args:
            relative_path: Vault-relative Markdown path.

        Returns:
            Authoritative note loaded from Markdown.
        """
        config = self._vault_config_store.current()
        safe_path = str(safe_relative_path(relative_path))
        metadata = await best_effort_index_lookup(
            lambda: self._repository.get_by_path(safe_path)
        )
        return await authoritative_note_from_path_async(
            vault_path=config.vault_path,
            relative_path=safe_path,
            alexandria_root=config.alexandria_root,
            indexed=metadata.note,
            index_error=(
                "INDEX_METADATA_UNAVAILABLE" if metadata.unavailable else None
            ),
        )

    async def _read_note_from_source_snapshot(
        self,
        *,
        note_id: str,
        indexed: ObsidianNote | None,
        metadata_unavailable: bool,
    ) -> ObsidianNote:
        """Resolve an exact id from one complete bounded source snapshot."""
        snapshot = await self._source_snapshot(self._source_scan_limit)
        if not snapshot.complete or snapshot.errors:
            raise ObsidianValidationError(
                "SOURCE_SCAN_INCOMPLETE: cannot prove requested note id is absent or unique"
            )
        matches = [payload for payload in snapshot.notes if payload.note_id == note_id]
        if len(matches) > 1:
            raise ObsidianValidationError(
                "AMBIGUOUS_SOURCE_NOTE_ID: multiple canonical Markdown notes "
                "match the requested id"
            )
        if not matches:
            raise ObsidianNotFoundError(f"Obsidian note not found: {note_id}")
        return authoritative_note_from_index(
            matches[0],
            indexed=indexed,
            index_error=(
                "INDEX_METADATA_UNAVAILABLE" if metadata_unavailable else None
            ),
            expected_note_id=note_id,
        )
