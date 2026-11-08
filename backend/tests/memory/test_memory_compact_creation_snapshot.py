"""Memory Compact creation-snapshot behavior tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import override

import anyio

from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.memory.infrastructure.repositories.memory_compacts.note_store import (
    MemoryCompactNoteStore,
)
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_serializer import (
    serialize_compact,
)

_NOTES_DIR = "Alexandria/Memory Compacts"
_COVERED_FROM = datetime(2026, 1, 1, tzinfo=UTC)
_COVERED_TO = datetime(2026, 1, 2, tzinfo=UTC)
_BODY = "A compact body used to check stable creation signatures."


class _CountingMemoryCompactNoteStore(MemoryCompactNoteStore):
    """Count complete canonical note-store scans during a test operation."""

    def __init__(self, vault_path: Path) -> None:
        super().__init__(vault_path=vault_path, relative_dir=_NOTES_DIR)
        self.read_all_count = 0

    @override
    def read_all(self) -> list[MemoryCompact]:
        """Count and perform one canonical compact scan."""
        self.read_all_count += 1
        return super().read_all()


def _repository(
    vault_path: Path,
    store: _CountingMemoryCompactNoteStore,
) -> ObsidianMemoryCompactRepository:
    """Use a counting store with the real cross-process repository adapter."""
    repository = ObsidianMemoryCompactRepository(
        vault_path=vault_path,
        relative_dir=_NOTES_DIR,
    )
    repository._store = store
    return repository


def _payload(
    *,
    project: str | None = "project-a",
    status: MemoryCompactStatus = MemoryCompactStatus.DRAFT,
    covered_to: datetime = _COVERED_TO,
    body: str = _BODY,
    source_id: str = "ctx-target",
) -> MemoryCompactCreate:
    return MemoryCompactCreate(
        project=project,
        covered_from=_COVERED_FROM,
        covered_to=covered_to,
        markdown_body=body,
        status=status,
        source_refs=(
            MemoryCompactSourceRefCreate(
                source_type="CONTEXT",
                source_id=source_id,
                title="Context source",
                detail_path=f"/memory/contexts/{source_id}",
            ),
        ),
    )


def _stored_compact(
    compact_id: str,
    *,
    project: str | None,
    status: MemoryCompactStatus,
    covered_to: datetime,
    body: str = _BODY,
    source_id: str = "ctx-target",
) -> MemoryCompact:
    """Build a stored entity whose signature can match a creation payload."""
    source_ref = MemoryCompactSourceRef(
        id=f"ref-{compact_id}",
        compact_id=compact_id,
        source_type="CONTEXT",
        source_id=source_id,
        title="Stored Context source",
        detail_path=f"/memory/contexts/{source_id}",
    )
    return MemoryCompact(
        id=compact_id,
        project=project,
        covered_from=covered_to - timedelta(days=1),
        covered_to=covered_to,
        markdown_body=body,
        status=status,
        source_refs=(source_ref,),
        created_at=covered_to,
        updated_at=covered_to,
        archived_at=None,
    )


def _write_fixture(
    store: MemoryCompactNoteStore,
    compact: MemoryCompact,
) -> None:
    """Write a serialized canonical note without counting a source scan."""
    path = store._compact_path(compact.id, created_at=compact.created_at)
    if path is None:
        raise AssertionError("fixture compact id is not a safe note id")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_compact(compact), encoding="utf-8")


def test_create_finds_duplicate_past_previous_page_with_one_source_scan(
    tmp_path: Path,
) -> None:
    """A duplicate beyond item 200 is found from one ordered store snapshot."""

    async def scenario() -> tuple[str, bool, int]:
        vault_path = tmp_path / "vault"
        store = _CountingMemoryCompactNoteStore(vault_path)
        repository = _repository(vault_path, store)
        for index in range(201):
            covered_to = _COVERED_TO + timedelta(days=index + 1)
            _write_fixture(
                store,
                _stored_compact(
                    f"decoy-{index:03d}",
                    project="project-a",
                    status=MemoryCompactStatus.DRAFT,
                    covered_to=covered_to,
                    body=f"Different body {index}",
                    source_id=f"ctx-decoy-{index}",
                ),
            )
        _write_fixture(
            store,
            _stored_compact(
                "target-duplicate",
                project="project-a",
                status=MemoryCompactStatus.DRAFT,
                covered_to=_COVERED_TO,
            ),
        )

        duplicate = await MemoryCompactService(repository=repository).create(_payload())
        return duplicate.id, duplicate.deduplicated, store.read_all_count

    compact_id, deduplicated, source_scan_count = anyio.run(scenario)

    assert compact_id == "target-duplicate"
    assert deduplicated is True
    assert source_scan_count == 1, (
        f"expected one source scan, observed {source_scan_count}"
    )


def test_creation_snapshot_filters_exact_project_and_status_in_coverage_order(
    tmp_path: Path,
) -> None:
    """Creation snapshots isolate exact project/status and retain newest-first order."""

    async def scenario() -> tuple[list[str], list[str], int]:
        vault_path = tmp_path / "vault"
        store = _CountingMemoryCompactNoteStore(vault_path)
        repository = _repository(vault_path, store)
        fixtures = (
            _stored_compact(
                "project-a-old",
                project="project-a",
                status=MemoryCompactStatus.DRAFT,
                covered_to=datetime(2026, 2, 2, tzinfo=UTC),
            ),
            _stored_compact(
                "project-a-new",
                project="project-a",
                status=MemoryCompactStatus.DRAFT,
                covered_to=datetime(2026, 2, 3, tzinfo=UTC),
            ),
            _stored_compact(
                "project-a-superseded",
                project="project-a",
                status=MemoryCompactStatus.SUPERSEDED,
                covered_to=datetime(2026, 3, 1, tzinfo=UTC),
            ),
            _stored_compact(
                "project-b-draft",
                project="project-b",
                status=MemoryCompactStatus.DRAFT,
                covered_to=datetime(2026, 4, 1, tzinfo=UTC),
            ),
            _stored_compact(
                "default-project-draft",
                project=None,
                status=MemoryCompactStatus.DRAFT,
                covered_to=datetime(2026, 5, 1, tzinfo=UTC),
            ),
        )
        for compact in fixtures:
            _write_fixture(store, compact)

        project_snapshot = await repository.creation_snapshot(
            project="project-a",
            status=MemoryCompactStatus.DRAFT,
        )
        default_snapshot = await repository.creation_snapshot(
            project=None,
            status=MemoryCompactStatus.DRAFT,
        )
        return (
            [compact.id for compact in project_snapshot],
            [compact.id for compact in default_snapshot],
            store.read_all_count,
        )

    project_ids, default_ids, source_scan_count = anyio.run(scenario)

    assert project_ids == ["project-a-new", "project-a-old"]
    assert default_ids == ["default-project-draft"]
    assert source_scan_count == 2


def test_create_distinguishes_project_and_status_and_creates_when_absent(
    tmp_path: Path,
) -> None:
    """Only an exact project/status signature deduplicates a create request."""

    async def scenario() -> tuple[str, str, str, bool, bool]:
        vault_path = tmp_path / "vault"
        store = _CountingMemoryCompactNoteStore(vault_path)
        repository = _repository(vault_path, store)
        _write_fixture(
            store,
            _stored_compact(
                "other-project",
                project="project-b",
                status=MemoryCompactStatus.DRAFT,
                covered_to=_COVERED_TO,
            ),
        )
        _write_fixture(
            store,
            _stored_compact(
                "other-status",
                project="project-a",
                status=MemoryCompactStatus.SUPERSEDED,
                covered_to=_COVERED_TO,
            ),
        )
        service = MemoryCompactService(repository=repository)

        exact_scope_create = await service.create(_payload())
        absent_signature_create = await service.create(_payload(source_id="ctx-absent"))
        return (
            exact_scope_create.id,
            absent_signature_create.id,
            "other-project",
            exact_scope_create.deduplicated,
            absent_signature_create.deduplicated,
        )

    first_id, absent_id, other_project_id, first_deduplicated, absent_deduplicated = (
        anyio.run(scenario)
    )

    assert first_id != other_project_id
    assert absent_id != first_id
    assert first_deduplicated is False
    assert absent_deduplicated is False
