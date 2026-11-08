"""Obsidian-backed Memory Compact repository implementation."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from asyncer import asyncify

from app.memory.application.memory_compacts.lifecycle.memory_compact_provenance import (
    MEMORY_COMPACT_GENERATION_REVISION,
    MEMORY_COMPACT_POLICY_VERSION,
    memory_compact_source_set_hash,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_signature import (
    compact_state_hash,
)
from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository import (
    IMemoryCompactRepository,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
)
from app.memory.infrastructure.repositories.memory_compacts.creation_lock import (
    MemoryCompactCreationLock,
)
from app.memory.infrastructure.repositories.memory_compacts.note_store import (
    MemoryCompactNoteStore,
)
from app.shared.exceptions.memory_compact_exceptions import (
    MemoryCompactNotFoundError,
    MemoryCompactReviewConflictError,
)
from app.shared.infrastructure.critical_task import run_critical_sync
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.types.types_convert_utils import aware_utc_datetime


class MemoryCompactCreateRepositoryDelegate:
    """Create Memory Compact notes over a shared Obsidian note store."""

    _store: MemoryCompactNoteStore
    _creation_lock: MemoryCompactCreationLock

    async def creation_snapshot(
        self,
        project: str | None,
        status: MemoryCompactStatus,
    ) -> list[MemoryCompact]:
        """Read one exact project/status snapshot for duplicate detection.

        Args:
            project: Exact project scope, including the default ``None`` project.
            status: Exact lifecycle status to inspect.

        Returns:
            Matching canonical compacts ordered by newest coverage first.
        """
        async with self._creation_lock.hold():
            stored_compacts = await run_critical_sync(self._store.read_all)
        compacts = [
            compact
            for compact in stored_compacts
            if compact.project == project and compact.status is status
        ]
        compacts.sort(key=lambda compact: compact.covered_to, reverse=True)
        return compacts

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
        source_refs = _source_refs(compact_id, payload)
        compact = MemoryCompact(
            id=compact_id,
            project=payload.project,
            covered_from=aware_utc_datetime(payload.covered_from),
            covered_to=aware_utc_datetime(payload.covered_to),
            markdown_body=payload.markdown_body,
            status=payload.status,
            source_refs=source_refs,
            created_at=now,
            updated_at=now,
            archived_at=None,
            review_verdict=payload.review_verdict,
            review_score=payload.review_score,
            review_max_score=payload.review_max_score,
            reviewed_at=payload.reviewed_at,
            reviewed_body_hash=payload.reviewed_body_hash,
            review_receipt_hash=payload.review_receipt_hash,
            source_set_hash=memory_compact_source_set_hash(source_refs),
            compaction_policy_version=MEMORY_COMPACT_POLICY_VERSION,
            generation_revision=MEMORY_COMPACT_GENERATION_REVISION,
            generated_at=now,
        )
        async with self._creation_lock.hold():
            await run_critical_sync(
                lambda: _persist_created_compact(self._store, compact)
            )
            return _require_compact(self._store, compact_id)


class MemoryCompactQueryRepositoryDelegate:
    """Read and page Memory Compact notes over a shared Obsidian note store."""

    _store: MemoryCompactNoteStore
    _creation_lock: MemoryCompactCreationLock

    async def get(self, compact_id: str) -> MemoryCompact | None:
        """Read one compact by id.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Matching compact, or None when absent.
        """
        async with self._creation_lock.hold():
            return self._store.get(compact_id)

    async def list_compacts(
        self,
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
        async with self._creation_lock.hold():
            stored_compacts = await asyncify(
                self._store.read_all,
                abandon_on_cancel=True,
            )()
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

    async def current(self, project: str | None = None) -> MemoryCompact | None:
        """Read current compact for a project.

        Args:
            project: Optional project filter; None addresses the default project.

        Returns:
            Current compact, or None when absent.
        """
        async with self._creation_lock.hold():
            compacts = [
                item
                for item in self._store.read_all()
                if item.status is MemoryCompactStatus.CURRENT
                and item.project == project
            ]
        compacts.sort(key=lambda item: item.updated_at, reverse=True)
        return compacts[0] if compacts else None


class MemoryCompactLifecycleRepositoryDelegate:
    """Mutate Memory Compact lifecycle over a shared Obsidian note store."""

    _store: MemoryCompactNoteStore
    _creation_lock: MemoryCompactCreationLock

    async def edit_draft(
        self, compact_id: str, markdown_body: str, expected_state_hash: str
    ) -> MemoryCompact:
        """Edit only an unchanged DRAFT and invalidate all prior review evidence.

        Args:
            compact_id: Existing canonical draft identity.
            markdown_body: Final semantic body supplied by the caller.
            expected_state_hash: Exact state digest observed before editing.

        Returns:
            Edited DRAFT with no reusable quality/promotion receipt.
        """
        async with self._creation_lock.hold():
            compact = _require_compact(self._store, compact_id)
            if (
                compact.status is not MemoryCompactStatus.DRAFT
                or compact_state_hash(compact) != expected_state_hash
            ):
                raise MemoryCompactReviewConflictError(
                    "MEMORY_COMPACT_DRAFT_CONFLICT: re-read the unchanged DRAFT before editing"
                )
            updated = replace(
                compact,
                markdown_body=markdown_body.strip(),
                updated_at=datetime.now(UTC),
                review_verdict=None,
                review_score=None,
                review_max_score=None,
                reviewed_at=None,
                reviewed_body_hash=None,
                review_receipt_hash=None,
            )
            self._store.write(updated)
            return updated

    async def mark_current(
        self,
        compact_id: str,
        review_verdict: MemoryCompactReviewVerdict | None = None,
        review_score: int | None = None,
        review_max_score: int | None = None,
        reviewed_at: datetime | None = None,
        expected_state_hash: str | None = None,
        reviewed_body_hash: str | None = None,
        review_receipt_hash: str | None = None,
    ) -> MemoryCompact:
        """Mark one compact current and supersede prior current for project.

        Args:
            compact_id: Memory Compact identifier.
            review_verdict: Latest quality review verdict for the promotion.
            review_score: Latest quality review total score.
            review_max_score: Latest quality review maximum score.
            reviewed_at: Review timestamp.
            reviewed_body_hash: Exact reviewed body identity.
            review_receipt_hash: Admitted source/body review receipt.
            expected_state_hash: Hash of the exact target state reviewed before
                persistence.

        Returns:
            Updated current compact.
        """
        async with self._creation_lock.hold():
            compact = _require_compact(self._store, compact_id)
            if (
                expected_state_hash is not None
                and compact_state_hash(compact) != expected_state_hash
            ):
                raise MemoryCompactReviewConflictError(
                    "MEMORY_COMPACT_REVIEW_CONFLICT: compact state changed "
                    "before persistence; re-review before applying"
                )
            snapshot = tuple(
                item
                for item in self._store.read_all()
                if item.project == compact.project
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
                reviewed_body_hash=reviewed_body_hash,
                review_receipt_hash=review_receipt_hash,
            )
            try:
                self._store.write(updated)
                _supersede_current_project(
                    self._store,
                    compact.project,
                    excluded_id=compact.id,
                )
                _assert_single_current(self._store, updated)
            except BaseException:
                try:
                    _restore_compact_snapshot(
                        self._store, snapshot, candidate_id=compact.id
                    )
                except BaseException as rollback_error:
                    raise MemoryCompactReviewConflictError(
                        "MEMORY_COMPACT_REVIEW_CONFLICT: promotion failed and "
                        "the previous compact state could not be restored"
                    ) from rollback_error
                raise
            return updated

    async def archive(self, compact_id: str) -> MemoryCompact:
        """Archive one compact.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Archived compact.
        """
        async with self._creation_lock.hold():
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
        async with self._creation_lock.hold():
            _require_compact(self._store, compact_id)
            self._store.delete(compact_id)


class ObsidianMemoryCompactRepository(
    MemoryCompactCreateRepositoryDelegate,
    MemoryCompactQueryRepositoryDelegate,
    MemoryCompactLifecycleRepositoryDelegate,
    IMemoryCompactRepository,
):
    """Assemble focused Memory Compact responsibilities over one note store."""

    def __init__(self, vault_path: str | Path, relative_dir: str | Path) -> None:
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
    """Execute persist created compact.

    Args:
        store: Store used by this operation.
        compact: Compact used by this operation.
    """
    snapshot = tuple(
        item for item in store.read_all() if item.project == compact.project
    )
    try:
        store.write(compact)
        if compact.status is MemoryCompactStatus.CURRENT:
            _supersede_current_project(
                store,
                compact.project,
                excluded_id=compact.id,
            )
            _assert_single_current(store, compact)
    except BaseException:
        _restore_compact_snapshot(store, snapshot, candidate_id=compact.id)
        raise


def _require_compact(
    store: MemoryCompactNoteStore,
    compact_id: str,
) -> MemoryCompact:
    """Execute require compact.

    Args:
        store: Store used by this operation.
        compact_id: Identifier for compact.

    Returns:
        MemoryCompact result produced by require compact.
    """
    compact = store.get(compact_id)
    if compact is None:
        raise MemoryCompactNotFoundError(f"Memory compact not found: {compact_id}")
    return compact


def _supersede_current_project(
    store: MemoryCompactNoteStore,
    project: str | None,
    excluded_id: str | None,
) -> None:
    """Execute supersede current project.

    Args:
        store: Store used by this operation.
        project: Project used by this operation.
        excluded_id: Identifier for excluded.
    """
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


def _assert_single_current(
    store: MemoryCompactNoteStore,
    expected_current: MemoryCompact,
) -> None:
    """Verify the persisted project has exactly one CURRENT compact."""
    current = [
        compact
        for compact in store.read_all()
        if compact.project == expected_current.project
        and compact.status is MemoryCompactStatus.CURRENT
    ]
    if len(current) != 1 or current[0].id != expected_current.id:
        raise MemoryCompactReviewConflictError(
            "MEMORY_COMPACT_REVIEW_CONFLICT: promotion did not persist exactly "
            "one CURRENT compact"
        )


def _restore_compact_snapshot(
    store: MemoryCompactNoteStore,
    snapshot: tuple[MemoryCompact, ...],
    *,
    candidate_id: str,
) -> None:
    """Restore the bounded project snapshot after a failed promotion."""
    if candidate_id not in {compact.id for compact in snapshot}:
        store.delete(candidate_id)
    for compact in snapshot:
        store.write(compact)


def _filter_compacts(
    compacts: list[MemoryCompact],
    project: str | None,
    status: MemoryCompactStatus | None,
    covered_after: datetime | None,
    covered_before: datetime | None,
) -> list[MemoryCompact]:
    """Execute filter compacts.

    Args:
        compacts: Compacts used by this operation.
        project: Project used by this operation.
        status: Status value used by this operation.
        covered_after: Covered after used by this operation.
        covered_before: Covered before used by this operation.

    Returns:
        list[MemoryCompact] result produced by filter compacts.
    """
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
    """Execute source refs.

    Args:
        compact_id: Identifier for compact.
        payload: Validated payload for this operation.

    Returns:
        tuple[MemoryCompactSourceRef, ...] result produced by source refs.
    """
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
