"""Regression coverage for source-owned exact Obsidian reads."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import anyio
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.application.service.notes.obsidian_note_service import (
    DEFAULT_SOURCE_SCAN_LIMIT,
    ObsidianNoteService,
)
from app.obsidian.application.service.vault.obsidian_vault_inventory_service import (
    ObsidianVaultInventoryService,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianReindexResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)


class _Repository:
    """Minimal read boundary fake; all mutation methods remain unused."""

    def __init__(
        self,
        *,
        by_id: ObsidianNote | None = None,
        by_path: ObsidianNote | None = None,
        failure: Exception | None = None,
    ) -> None:
        self._by_id = by_id
        self._by_path = by_path
        self._failure = failure

    async def get_by_id(self, _note_id: str) -> ObsidianNote | None:
        if self._failure is not None:
            raise self._failure
        return self._by_id

    async def get_by_path(self, _relative_path: str) -> ObsidianNote | None:
        if self._failure is not None:
            raise self._failure
        return self._by_path


def _markdown(note_id: str, title: str, body: str) -> str:
    return (
        "---\n"
        "alexandria_type: job_plan\n"
        f"id: {note_id}\n"
        f"title: {title}\n"
        "status: active\n"
        "project: source-read-tests\n"
        "---\n\n"
        f"# {title}\n\n{body}\n"
    )


def _source_path(tmp_path: Path, relative_path: str, content: str) -> Path:
    path = tmp_path / "vault" / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _indexed_row(note_id: str, relative_path: str, content_hash: str) -> ObsidianNote:
    return ObsidianNote(
        note_id=note_id,
        relative_path=relative_path,
        alexandria_type=AlexandriaNoteType.JOB_PLAN,
        title="Cached note",
        status="active",
        tags=(),
        project="source-read-tests",
        source="test",
        content_hash=content_hash,
        frontmatter={"id": note_id},
        body="cached body",
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=1,
        modified_at=datetime.now(UTC),
        indexed_at=datetime.now(UTC),
    )


def _service(
    tmp_path: Path,
    repository: _Repository,
    *,
    source_scan_limit: int = DEFAULT_SOURCE_SCAN_LIMIT,
) -> tuple[ObsidianNoteService, list[int]]:
    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)
    (vault_path / "Alexandria").mkdir(parents=True, exist_ok=True)
    config_store = ObsidianVaultConfigStore(
        default_vault_path=str(vault_path),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    inventory = ObsidianVaultInventoryService(config_store)
    reindex_calls: list[int] = []

    async def reindex() -> ObsidianReindexResult:
        reindex_calls.append(1)
        return ObsidianReindexResult(
            files_seen=0,
            files_indexed=0,
            files_skipped=0,
            stale_marked=0,
        )

    async def mark_context_superseded(**_: str) -> None:
        return None

    service = ObsidianNoteService(
        repository=cast(IObsidianIndexRepository, repository),
        vault_config_store=config_store,
        reindex=reindex,
        mark_context_superseded=mark_context_superseded,
        index_maintenance_coordinator=IndexMaintenanceCoordinator(),
        source_snapshot=inventory.source_snapshot,
        source_scan_limit=source_scan_limit,
    )
    return service, reindex_calls


def test_path_read_uses_canonical_source_without_index_or_reindex(
    tmp_path: Path,
) -> None:
    """A readable managed Markdown note remains available without metadata."""
    relative_path = "Alexandria/Notes/Source.md"
    _source_path(
        tmp_path, relative_path, _markdown("source-note", "Source", "fresh body")
    )
    service, reindex_calls = _service(tmp_path, _Repository())

    note = anyio.run(service.read_note_by_path, relative_path)

    assert note.note_id == "source-note"
    assert note.body.endswith("fresh body")
    assert note.index_status is ObsidianIndexStatus.UNINDEXED
    assert note.indexed_at is None
    assert note.error_message is None
    assert reindex_calls == []


def test_path_read_marks_projection_unindexed_when_metadata_is_unavailable(
    tmp_path: Path,
) -> None:
    """A persistence read failure must not block a canonical source read."""
    relative_path = "Alexandria/Notes/Metadata Failure.md"
    _source_path(
        tmp_path,
        relative_path,
        _markdown("metadata-failure", "Metadata Failure", "source survives"),
    )
    service, reindex_calls = _service(
        tmp_path,
        _Repository(failure=SQLAlchemyError("metadata unavailable")),
    )

    note = anyio.run(service.read_note_by_path, relative_path)

    assert note.note_id == "metadata-failure"
    assert note.index_status is ObsidianIndexStatus.UNINDEXED
    assert note.indexed_at is None
    assert note.error_message == "INDEX_METADATA_UNAVAILABLE"
    assert reindex_calls == []


def test_path_read_marks_cached_projection_stale_after_source_change(
    tmp_path: Path,
) -> None:
    """A changed source must never be served as a fresh cached projection."""
    relative_path = "Alexandria/Notes/Stale.md"
    _source_path(tmp_path, relative_path, _markdown("stale-note", "Stale", "new body"))
    service, _ = _service(
        tmp_path,
        _Repository(
            by_path=_indexed_row(
                relative_path=relative_path, note_id="stale-note", content_hash="0" * 64
            )
        ),
    )

    note = anyio.run(service.read_note_by_path, relative_path)

    assert note.body.endswith("new body")
    assert note.index_status is ObsidianIndexStatus.STALE
    assert note.error_message == "INDEX_CONTENT_STALE"


def test_path_read_marks_cached_projection_stale_after_frontmatter_change(
    tmp_path: Path,
) -> None:
    """A metadata-only source edit cannot remain an indexed current projection."""
    relative_path = "Alexandria/Notes/Metadata Stale.md"
    path = _source_path(
        tmp_path,
        relative_path,
        _markdown("metadata-stale", "Original", "same body"),
    )
    payload = note_index_from_path(
        path,
        relative_path,
        alexandria_root="Alexandria",
    )
    assert payload is not None
    indexed = _indexed_row(
        relative_path=relative_path,
        note_id="metadata-stale",
        content_hash=payload.content_hash,
    )
    indexed.frontmatter = dict(payload.frontmatter)
    path.write_text(
        _markdown("metadata-stale", "Original", "same body").replace(
            "status: active", "status: reviewed"
        ),
        encoding="utf-8",
    )
    service, _ = _service(tmp_path, _Repository(by_path=indexed))

    note = anyio.run(service.read_note_by_path, relative_path)

    assert note.body.endswith("same body")
    assert note.index_status is ObsidianIndexStatus.STALE
    assert note.error_message == "INDEX_CONTENT_STALE"


def test_id_read_rejects_stale_mapping_instead_of_returning_wrong_source(
    tmp_path: Path,
) -> None:
    """An indexed id mapping cannot mask a source id mismatch."""
    relative_path = "Alexandria/Notes/Changed ID.md"
    _source_path(tmp_path, relative_path, _markdown("actual-id", "Changed", "body"))
    service, reindex_calls = _service(
        tmp_path,
        _Repository(
            by_id=_indexed_row(
                relative_path=relative_path,
                note_id="requested-id",
                content_hash="0" * 64,
            )
        ),
    )

    with pytest.raises(ObsidianValidationError, match="SOURCE_ID_MISMATCH"):
        anyio.run(service.read_note, "requested-id")
    assert reindex_calls == []


def test_id_fallback_reports_duplicate_source_ids_without_reindex(
    tmp_path: Path,
) -> None:
    """A source scan with duplicate ids must fail closed as ambiguous."""
    _source_path(
        tmp_path,
        "Alexandria/Notes/First.md",
        _markdown("duplicate-id", "First", "one"),
    )
    _source_path(
        tmp_path,
        "Alexandria/Notes/Second.md",
        _markdown("duplicate-id", "Second", "two"),
    )
    service, reindex_calls = _service(tmp_path, _Repository())

    with pytest.raises(ObsidianValidationError, match="AMBIGUOUS_SOURCE_NOTE_ID"):
        anyio.run(service.read_note, "duplicate-id")
    assert reindex_calls == []


def test_exact_read_rejects_traversal_and_symlink_paths(tmp_path: Path) -> None:
    """Exact source reads preserve managed-root and symlink confinement."""
    outside = tmp_path / "outside.md"
    outside.write_text(_markdown("outside", "Outside", "secret"), encoding="utf-8")
    link = tmp_path / "vault" / "Alexandria" / "Notes" / "Outside.md"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    service, _ = _service(tmp_path, _Repository())

    with pytest.raises(ObsidianValidationError, match="inside the vault"):
        anyio.run(service.read_note_by_path, "../outside.md")
    with pytest.raises(ObsidianValidationError, match="PATH_SECURITY_VIOLATION"):
        anyio.run(service.read_note_by_path, "Alexandria/Notes/Outside.md")


def test_exact_read_reports_source_missing_even_when_cached_row_exists(
    tmp_path: Path,
) -> None:
    """A missing source never falls back to cached body content."""
    relative_path = "Alexandria/Notes/Missing.md"
    service, reindex_calls = _service(
        tmp_path,
        _Repository(
            by_path=_indexed_row(
                relative_path=relative_path,
                note_id="missing-source",
                content_hash="0" * 64,
            )
        ),
    )

    with pytest.raises(ObsidianNotFoundError):
        anyio.run(service.read_note_by_path, relative_path)
    assert reindex_calls == []


def test_id_read_recovers_a_unique_note_after_stale_path_mapping(
    tmp_path: Path,
) -> None:
    """A moved source can be recovered only through an independent exact-id scan."""
    old_path = "Alexandria/Notes/Old Location.md"
    new_path = "Alexandria/Notes/New Location.md"
    _source_path(tmp_path, new_path, _markdown("moved-note", "Moved", "body"))
    service, reindex_calls = _service(
        tmp_path,
        _Repository(
            by_id=_indexed_row(
                relative_path=old_path,
                note_id="moved-note",
                content_hash="0" * 64,
            )
        ),
    )

    note = anyio.run(service.read_note, "moved-note")

    assert note.relative_path == new_path
    assert note.index_status is ObsidianIndexStatus.STALE
    assert note.error_message == "INDEX_PATH_STALE"
    assert reindex_calls == []


def test_source_snapshot_reports_traversal_and_note_limits(tmp_path: Path) -> None:
    """The source snapshot bounds traversal and parsed-note cardinality."""
    _source_path(
        tmp_path, "Alexandria/Notes/First.md", _markdown("first", "First", "one")
    )
    _source_path(
        tmp_path,
        "Alexandria/Notes/Second.md",
        _markdown("second", "Second", "two"),
    )
    config = ObsidianVaultConfigStore(
        default_vault_path=str(tmp_path / "vault"),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    inventory = ObsidianVaultInventoryService(config)

    async def read_snapshot():
        return await inventory.source_snapshot(
            10,
            max_entries=1,
            max_total_bytes=1024 * 1024,
            max_file_bytes=1024 * 1024,
            max_errors=4,
        )

    snapshot = anyio.run(read_snapshot)

    assert snapshot.complete is False
    assert "SOURCE_SCAN_LIMIT_EXCEEDED" in snapshot.errors
    assert snapshot.entries_seen == 2
    assert snapshot.scanned_paths <= 1


def test_source_snapshot_bounds_file_bytes_and_error_aggregation(
    tmp_path: Path,
) -> None:
    """Oversized and malformed sources produce bounded stable diagnostics."""
    _source_path(
        tmp_path,
        "Alexandria/Notes/Oversized.md",
        _markdown("oversized", "Oversized", "x" * 128),
    )
    for index in range(4):
        _source_path(
            tmp_path,
            f"Alexandria/Notes/Malformed {index}.md",
            "---\nalexandria_type: invalid\nid: malformed\n---\n\n# Bad\n",
        )
    config = ObsidianVaultConfigStore(
        default_vault_path=str(tmp_path / "vault"),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    inventory = ObsidianVaultInventoryService(config)

    async def read_snapshot():
        return await inventory.source_snapshot(
            10,
            max_entries=100,
            max_total_bytes=1024 * 1024,
            max_file_bytes=32,
            max_errors=2,
        )

    snapshot = anyio.run(read_snapshot)

    assert snapshot.complete is False
    assert "SOURCE_SCAN_LIMIT_EXCEEDED" in snapshot.errors
    assert len(snapshot.errors) <= 2
    assert snapshot.total_bytes == 0


def test_source_snapshot_rejects_symlink_directories(tmp_path: Path) -> None:
    """Bounded discovery must not traverse a symlinked managed directory."""
    external = tmp_path / "external"
    external.mkdir()
    (external / "Escaped.md").write_text(
        _markdown("escaped", "Escaped", "outside"),
        encoding="utf-8",
    )
    managed = tmp_path / "vault" / "Alexandria" / "Notes"
    managed.mkdir(parents=True)
    (managed / "External").symlink_to(external, target_is_directory=True)
    config = ObsidianVaultConfigStore(
        default_vault_path=str(tmp_path / "vault"),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    inventory = ObsidianVaultInventoryService(config)

    async def read_snapshot():
        return await inventory.source_snapshot(
            10,
            max_entries=100,
            max_total_bytes=1024 * 1024,
            max_file_bytes=1024 * 1024,
            max_errors=4,
        )

    snapshot = anyio.run(read_snapshot)

    assert snapshot.complete is False
    assert "PATH_SECURITY_VIOLATION" in snapshot.errors
    assert snapshot.notes == ()


def test_exact_read_maps_malformed_source_to_typed_validation_error(
    tmp_path: Path,
) -> None:
    """Malformed source parser failures do not cross the domain boundary raw."""
    relative_path = "Alexandria/Notes/Malformed.md"
    _source_path(
        tmp_path,
        relative_path,
        "---\nalexandria_type: invalid\nid: malformed\n---\n\n# Bad\n",
    )
    service, _ = _service(tmp_path, _Repository())

    with pytest.raises(ObsidianValidationError, match="FRONTMATTER_PARSE_ERROR"):
        anyio.run(service.read_note_by_path, relative_path)
