"""Obsidian-backed Memory Compact repository implementation."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
)
from app.memory.domain.repositories.memory_compact_repository import (
    IMemoryCompactRepository,
)
from app.memory.domain.repositories.memory_compact_repository_contracts import (
    MemoryCompactCreate,
)
from app.memory.infrastructure.repositories.memory_compacts.creation_lock import (
    MemoryCompactCreationLock,
)
from app.memory.infrastructure.repositories.memory_compacts.critical_task import (
    wait_for_critical_task,
)
from app.memory.infrastructure.repositories.memory_compacts.note_store import (
    MemoryCompactNoteStore,
)
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactNotFoundError
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.types.types_convert_utils import aware_utc_datetime


class MemoryCompactCreateRepositoryDelegate:
    """Create Memory Compact notes over a shared Obsidian note store."""

    _store: MemoryCompactNoteStore
    _creation_lock: MemoryCompactCreationLock

    def creation_guard(self) -> AbstractAsyncContextManager[None]:
        """Serialize the full application-level check-and-create section.

        Returns:
            Async context manager backed by a local cross-process file lock.
        """
        return self._creation_lock.hold()

    async def create(self, payload: MemoryCompactCreate) -> MemoryCompact:
        """Create one Memory Compact note and source-reference frontmatter.

        Args:
            payload: Memory Compact creation contract.

        Returns:
            Created Memory Compact entity.
        """
        now = datetime.now(UTC)
        compact_id = new_uuid()
        compact = MemoryCompact(
            id=compact_id,
            project=payload.project,
            covered_from=aware_utc_datetime(payload.covered_from),
            covered_to=aware_utc_datetime(payload.covered_to),
            markdown_body=payload.markdown_body,
            status=payload.status,
            source_refs=_source_refs(compact_id, payload),
            created_at=now,
            updated_at=now,
            archived_at=None,
            review_verdict=payload.review_verdict,
            review_score=payload.review_score,
            review_max_score=payload.review_max_score,
            reviewed_at=payload.reviewed_at,
        )
        persistence_task = asyncio.create_task(
            asyncio.to_thread(
                _persist_created_compact,
                self._store,
                compact,
            )
        )
        await wait_for_critical_task(persistence_task)
        return compact


class MemoryCompactQueryRepositoryDelegate:
    """Read and page Memory Compact notes over a shared Obsidian note store."""

    _store: MemoryCompactNoteStore

    async def get(self, compact_id: str) -> MemoryCompact | None:
        """Read one compact by id.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Matching compact, or None when absent.
        """
        return self._store.get(compact_id)

    async def list_compacts(
        self,
        *,
        project: str | None = None,
        status: MemoryCompactStatus | None = None,
        covered_after: datetime | None = None,
        covered_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryCompact], int]:
        """List compacts and total count.

        Args:
            project: Project filter.
            status: Lifecycle status filter.
            covered_after: Coverage-overlap lower bound.
            covered_before: Coverage-overlap upper bound.
            limit: Maximum number of rows to return.
            offset: Number of rows to skip.

        Returns:
            Page of compacts and total matching count.
        """
        stored_compacts = await asyncio.to_thread(self._store.read_all)
        compacts = _filter_compacts(
            stored_compacts,
            project=project,
            status=status,
            covered_after=covered_after,
            covered_before=covered_before,
        )
        compacts.sort(key=lambda item: item.covered_to, reverse=True)
        total = len(compacts)
        return compacts[offset : offset + limit], total

    async def current(self, *, project: str | None = None) -> MemoryCompact | None:
        """Read current compact for a project.

        Args:
            project: Optional project filter; None addresses the default project.

        Returns:
            Current compact, or None when absent.
        """
        compacts = [
            item
            for item in self._store.read_all()
            if item.status is MemoryCompactStatus.CURRENT and item.project == project
        ]
        compacts.sort(key=lambda item: item.updated_at, reverse=True)
        return compacts[0] if compacts else None


class MemoryCompactLifecycleRepositoryDelegate:
    """Mutate Memory Compact lifecycle over a shared Obsidian note store."""

    _store: MemoryCompactNoteStore

    async def mark_current(
        self,
        compact_id: str,
        *,
        review_verdict: MemoryCompactReviewVerdict | None = None,
        review_score: int | None = None,
        review_max_score: int | None = None,
        reviewed_at: datetime | None = None,
    ) -> MemoryCompact:
        """Mark one compact current and supersede prior current for project.

        Args:
            compact_id: Memory Compact identifier.
            review_verdict: Latest librarian review verdict for the promotion.
            review_score: Latest librarian review total score.
            review_max_score: Latest librarian review maximum score.
            reviewed_at: Review timestamp.

        Returns:
            Updated current compact.
        """
        compact = _require_compact(self._store, compact_id)
        _supersede_current_project(
            self._store,
            compact.project,
            excluded_id=compact.id,
        )
        updated = replace(
            compact,
            status=MemoryCompactStatus.CURRENT,
            updated_at=datetime.now(UTC),
            archived_at=None,
            review_verdict=review_verdict,
            review_score=review_score,
            review_max_score=review_max_score,
            reviewed_at=reviewed_at,
        )
        self._store.write(updated)
        return updated

    async def archive(self, compact_id: str) -> MemoryCompact:
        """Archive one compact.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Archived compact.
        """
        compact = _require_compact(self._store, compact_id)
        now = datetime.now(UTC)
        updated = replace(
            compact,
            status=MemoryCompactStatus.ARCHIVED,
            updated_at=now,
            archived_at=now,
        )
        self._store.write(updated)
        return updated

    async def delete(self, compact_id: str) -> None:
        """Hard delete one compact note.

        Args:
            compact_id: Memory Compact identifier.
        """
        _require_compact(self._store, compact_id)
        self._store.delete(compact_id)


class ObsidianMemoryCompactRepository(
    MemoryCompactCreateRepositoryDelegate,
    MemoryCompactQueryRepositoryDelegate,
    MemoryCompactLifecycleRepositoryDelegate,
    IMemoryCompactRepository,
):
    """Assemble focused Memory Compact responsibilities over one note store."""

    def __init__(self, *, vault_path: str | Path, relative_dir: str | Path) -> None:
        """Initialize repository.

        Args:
            vault_path: Obsidian vault root path.
            relative_dir: Relative folder for Memory Compact notes.
        """
        self._store = MemoryCompactNoteStore(
            vault_path=vault_path,
            relative_dir=relative_dir,
        )
        self._creation_lock = MemoryCompactCreationLock(
            vault_path=vault_path,
            relative_dir=relative_dir,
        )


def _persist_created_compact(
    store: MemoryCompactNoteStore,
    compact: MemoryCompact,
) -> None:
    if compact.status is MemoryCompactStatus.CURRENT:
        _supersede_current_project(
            store,
            compact.project,
            excluded_id=None,
        )
    store.write(compact)


def _require_compact(
    store: MemoryCompactNoteStore,
    compact_id: str,
) -> MemoryCompact:
    compact = store.get(compact_id)
    if compact is None:
        raise MemoryCompactNotFoundError(f"Memory compact not found: {compact_id}")
    return compact


def _supersede_current_project(
    store: MemoryCompactNoteStore,
    project: str | None,
    *,
    excluded_id: str | None,
) -> None:
    now = datetime.now(UTC)
    for compact in store.read_all():
        if (
            compact.status is MemoryCompactStatus.CURRENT
            and compact.project == project
            and compact.id != excluded_id
        ):
            store.write(
                replace(
                    compact,
                    status=MemoryCompactStatus.SUPERSEDED,
                    updated_at=now,
                )
            )


def _filter_compacts(
    compacts: list[MemoryCompact],
    *,
    project: str | None,
    status: MemoryCompactStatus | None,
    covered_after: datetime | None,
    covered_before: datetime | None,
) -> list[MemoryCompact]:
    if project is not None:
        compacts = [item for item in compacts if item.project == project]
    if status is not None:
        compacts = [item for item in compacts if item.status is status]
    if covered_after is not None:
        lower_bound = aware_utc_datetime(covered_after)
        compacts = [item for item in compacts if item.covered_to >= lower_bound]
    if covered_before is not None:
        upper_bound = aware_utc_datetime(covered_before)
        compacts = [item for item in compacts if item.covered_from <= upper_bound]
    return compacts


def _source_refs(
    compact_id: str,
    payload: MemoryCompactCreate,
) -> tuple[MemoryCompactSourceRef, ...]:
    return tuple(
        MemoryCompactSourceRef(
            id=new_uuid(),
            compact_id=compact_id,
            source_type=source_ref.source_type,
            source_id=source_ref.source_id,
            title=source_ref.title,
            detail_path=source_ref.detail_path,
            source_hash=source_ref.source_hash,
        )
        for source_ref in payload.source_refs
    )
