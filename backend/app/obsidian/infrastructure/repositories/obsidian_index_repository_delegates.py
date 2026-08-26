"""Focused delegation mixins for the SQLAlchemy Obsidian index facade."""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianContextDuplicateQuery,
    ObsidianNoteIndex,
    ObsidianSearchQuery,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianNote,
    ObsidianSearchHit,
)
from app.obsidian.infrastructure.repositories.obsidian_index_error_store import (
    ObsidianIndexErrorStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_query_store import (
    ObsidianIndexQueryStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_write_store import (
    ObsidianIndexWriteStore,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianIndexWriteError


class ObsidianIndexWriteRepositoryDelegate:
    """Delegate table setup and index write operations."""

    _session: AsyncSession
    _write_store: ObsidianIndexWriteStore

    async def upsert_note(self, payload: ObsidianNoteIndex) -> ObsidianNote:
        """Create or update one indexed note and its chunks.

        Args:
            payload: Indexed note payload.

        Returns:
            Persisted note entity.
        """
        try:
            async with self._session.begin_nested():
                return await self._upsert_note(payload)
        except SQLAlchemyError as exc:
            raise ObsidianIndexWriteError(
                f"failed to index Obsidian note: {payload.relative_path}"
            ) from exc

    async def _upsert_note(self, payload: ObsidianNoteIndex) -> ObsidianNote:
        """Execute upsert note.

        Args:
            payload: Validated payload for this operation.

        Returns:
            ObsidianNote result produced by upsert note.
        """
        return await self._write_store._upsert_note(payload)

    async def mark_missing_stale(self, relative_paths: set[str]) -> int:
        """Mark indexed notes absent from the current scan as stale.

        Args:
            relative_paths: Paths observed during the current scan.

        Returns:
            Number of notes marked stale.
        """
        return await self._write_store.mark_missing_stale(relative_paths)

    async def resolve_edge_targets(self) -> int:
        """Resolve late-indexed edge target ids from canonical paths.

        Returns:
            Number of edge rows updated.
        """
        return await self._write_store.resolve_edge_targets()


class ObsidianIndexQueryRepositoryDelegate:
    """Delegate note, search, and status queries."""

    _query_store: ObsidianIndexQueryStore

    async def get_by_id(self, note_id: str) -> ObsidianNote | None:
        """Read one indexed note by stable id.

        Args:
            note_id: Stable note id.

        Returns:
            Note entity when found.
        """
        return await self._query_store.get_by_id(note_id)

    async def get_by_path(self, relative_path: str) -> ObsidianNote | None:
        """Read one indexed note by vault-relative path.

        Args:
            relative_path: Vault-relative path.

        Returns:
            Note entity when found.
        """
        return await self._query_store.get_by_path(relative_path)

    async def find_context_duplicate(
        self,
        query: ObsidianContextDuplicateQuery,
    ) -> ObsidianNote | None:
        """Return a Context with the same identity and content hash.

        Args:
            query: Canonical duplicate lookup constraints.

        Returns:
            Existing duplicate Context when found.
        """
        return await self._query_store.find_context_duplicate(query)

    async def search(self, query: ObsidianSearchQuery) -> list[ObsidianSearchHit]:
        """Search indexed notes using the PostgreSQL FTS index.

        Args:
            query: Search filters and query text.

        Returns:
            Ranked search hits.
        """
        return await self._query_store.search(query)

    async def count_by_status(self) -> tuple[int, int, int]:
        """Return indexed, stale, and error note counts.

        Returns:
            Indexed, stale, and error counts.
        """
        return await self._query_store.count_by_status()

    async def list_indexed_notes(self) -> tuple[ObsidianNote, ...]:
        """Return all indexed managed notes in deterministic order.

        Returns:
            Immutable sequence delegated from the focused query store.
        """
        return await self._query_store.list_indexed_notes()

    async def projection_source_revision(self) -> str:
        """Return the current indexed-note projection source revision.

        Returns:
            Deterministic revision token delegated from the focused query store.
        """
        return await self._query_store.projection_source_revision()


class ObsidianIndexErrorRepositoryDelegate:
    """Delegate structured index error persistence."""

    _error_store: ObsidianIndexErrorStore

    async def record_index_error(self, error: ObsidianIndexError) -> None:
        """Persist one structured reindex error.

        Args:
            error: Structured note indexing failure.
        """
        await self._error_store.record_index_error(error)

    async def list_index_errors(self, limit: int = 20) -> list[ObsidianIndexError]:
        """Return recent structured reindex errors.

        Args:
            limit: Maximum number of errors to return.

        Returns:
            Recent structured indexing failures.
        """
        return await self._error_store.list_index_errors(limit)
