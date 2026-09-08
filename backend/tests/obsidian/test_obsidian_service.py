"""Obsidian vault service behavior tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.application.service.vault import obsidian_vault_lifecycle_service
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianChunkIndex,
    ObsidianNoteIndex,
    ObsidianSaveNote,
    ObsidianSearchQuery,
    ObsidianVaultInventoryRequest,
    ObsidianVaultMoveApplyRequest,
    ObsidianVaultMovePlanRequest,
    ObsidianVaultMoveRequest,
    ObsidianVaultSettingsUpdate,
    ObsidianWriteNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianFrontmatterMode,
    ObsidianIndexStatus,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
    ObsidianWriteOperation,
)
from app.obsidian.infrastructure.markdown.native_context_reindex_manifest import (
    create_native_context_reindex_manifest_validator,
)
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIdentityConflictError,
    ObsidianIndexWriteError,
    ObsidianNotFoundError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
    ObsidianWriteTargetNotFoundError,
)
from app.shared.infrastructure.database import Database
from app.shared.serialization.orjson_codec import loads_json

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


async def _service(
    tmp_path: Path,
    *,
    coordinator: IndexMaintenanceCoordinator | None = None,
    alexandria_root: str = "Alexandria",
) -> tuple[Database, AsyncSession, ObsidianService]:
    database = Database(database_url=_database_url(), create_schema=True)
    await database.initialize()
    session = database.session()
    service = ObsidianService(
        repository=SqlAlchemyObsidianIndexRepository(session=session),
        vault_path=str(tmp_path / "vault"),
        alexandria_root=alexandria_root,
        index_maintenance_coordinator=coordinator,
        context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
    )
    return database, session, service


def test_note_write_waits_for_active_vault_reindex_lane(tmp_path: Path) -> None:
    """Note persistence must not overlap an active vault index writer."""

    async def scenario() -> tuple[bool, str]:
        coordinator = IndexMaintenanceCoordinator()
        database, session, service = await _service(
            tmp_path,
            coordinator=coordinator,
        )
        maintenance_entered = anyio.Event()
        release_maintenance = anyio.Event()
        write_finished = anyio.Event()
        note_path = "Alexandria/Concurrency/Queued Note.md"
        absolute_path = tmp_path / "vault" / note_path

        async def maintenance() -> None:
            async with coordinator.operation("vault_reindex"):
                maintenance_entered.set()
                await release_maintenance.wait()

        async def writer() -> None:
            await maintenance_entered.wait()
            await service.save_note(
                ObsidianSaveNote(
                    title="Queued Note",
                    body="# Queued Note\n",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="queued-note",
                    relative_path=note_path,
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            write_finished.set()

        try:
            async with anyio.create_task_group() as group:
                group.start_soon(maintenance)
                group.start_soon(writer)
                await maintenance_entered.wait()
                with anyio.move_on_after(0.05):
                    await write_finished.wait()
                assert not write_finished.is_set()
                assert not absolute_path.exists()
                release_maintenance.set()

            note = await service.read_note("queued-note")
            return absolute_path.exists(), note.index_status.value
        finally:
            await session.close()
            await database.shutdown()

    exists, index_status = anyio.run(scenario)

    assert exists is True
    assert index_status == ObsidianIndexStatus.INDEXED.value


def test_obsidian_index_bounds_and_overlaps_large_canonical_note_chunks(
    tmp_path: Path,
) -> None:
    """Canonical Obsidian indexing should use bounded overlapping search chunks."""

    async def scenario() -> list[str]:
        database, session, service = await _service(tmp_path)
        try:
            note_id = "context_large_search_chunk"
            await service.save_note(
                ObsidianSaveNote(
                    title="Large Search Chunk",
                    body="# Large Search Chunk\n\n"
                    + " ".join(f"검색토큰-{index}" for index in range(600)),
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id=note_id,
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            rows = await session.scalars(
                select(ObsidianChunkORM)
                .where(ObsidianChunkORM.note_id == note_id)
                .order_by(ObsidianChunkORM.chunk_index)
            )
            return [chunk.text for chunk in rows.all()]
        finally:
            await session.close()
            await database.shutdown()

    chunk_texts = anyio.run(scenario)

    assert len(chunk_texts) > 2
    assert all(len(chunk_text) <= 1400 for chunk_text in chunk_texts)
    first_tail = set(chunk_texts[0].split()[-15:])
    second_head = set(chunk_texts[1].split()[:30])
    assert len(first_tail & second_head) >= 5


def test_obsidian_init_creates_frontmatter_start_note(tmp_path: Path) -> None:
    """Initializing the vault should create a managed START_HERE note."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            note = await service.initialize_vault()
            status = await service.status()
        finally:
            await session.close()
            await database.shutdown()

        note_path = tmp_path / "vault" / "Alexandria" / "START_HERE.md"
        note_text = note_path.read_text(encoding="utf-8")
        assert note.note_id == "alexandria_start_here"
        assert status.indexed_notes == 1
        assert "alexandria_type: context" in note_text
        assert "id: alexandria_start_here" in note_text
        assert (tmp_path / "vault" / "Alexandria" / "_Inbox" / "Captures").exists()
        assert (tmp_path / "vault" / "Alexandria" / "_Inbox" / "To Promote").exists()
        assert (tmp_path / "vault" / "Alexandria" / "Contexts" / "Projects").exists()
        assert not (
            tmp_path / "vault" / "Alexandria" / "Contexts" / "Project Context"
        ).exists()

    anyio.run(scenario)


def test_obsidian_reindex_searches_frontmatter_notes(tmp_path: Path) -> None:
    """Reindex should classify official notes and search them through PostgreSQL FTS."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            notes_dir = tmp_path / "vault" / "Alexandria" / "Contexts" / "Decisions"
            notes_dir.mkdir(parents=True)
            (notes_dir / "Storage.md").write_text(
                "---\n"
                "alexandria_type: context\n"
                "id: ctx_storage\n"
                "title: Obsidian Storage\n"
                "tags:\n"
                "  - obsidian\n"
                "status: active\n"
                "created_at: '2026-05-25'\n"
                "source: human\n"
                "project: heterarchy-alexandria\n"
                "---\n\n"
                "# Obsidian Storage\n\nPostgreSQL is a rebuildable search cache.\n",
                encoding="utf-8",
            )
            result = await service.reindex()
            hits = await service.search(
                ObsidianSearchQuery(query="rebuildable search cache", limit=3),
                refresh=False,
            )
        finally:
            await session.close()
            await database.shutdown()

        assert result.files_seen == 1
        assert result.files_indexed == 1
        assert [(hit.note.note_id, hit.note.relative_path) for hit in hits] == [
            ("ctx_storage", "Alexandria/Contexts/Decisions/Storage.md")
        ]

    anyio.run(scenario)


def test_obsidian_reindex_excludes_hidden_internal_vault_directories(
    tmp_path: Path,
) -> None:
    """Vault-root scans must not treat Obsidian trash or metadata as managed notes."""

    async def scenario() -> tuple[int, int, tuple[str, ...], list[str]]:
        database, session, service = await _service(tmp_path, alexandria_root=".")
        vault = tmp_path / "vault"
        canonical_dir = vault / "Contexts" / "Projects"
        canonical_dir.mkdir(parents=True)
        canonical_body = (
            "---\nalexandria_type: context\nid: ctx_identity_winner\n"
            "title: Canonical Winner\nstatus: active\n---\n\n# Canonical Winner\n"
        )
        (canonical_dir / "Canonical Winner.md").write_text(
            canonical_body,
            encoding="utf-8",
        )
        trash_dir = vault / ".trash" / "Alexandria" / "Identity Quarantine"
        trash_dir.mkdir(parents=True)
        (trash_dir / "Historical Copy.md").write_text(
            canonical_body.replace("Canonical Winner", "Historical Copy"),
            encoding="utf-8",
        )
        obsidian_dir = vault / ".obsidian" / "plugins" / "example"
        obsidian_dir.mkdir(parents=True)
        (obsidian_dir / "README.md").write_text("# Plugin Metadata\n", encoding="utf-8")
        try:
            result = await service.reindex()
            paths = await service.managed_markdown_paths()
        finally:
            await session.close()
            await database.shutdown()
        return result.files_seen, result.files_indexed, result.errors, paths

    files_seen, files_indexed, errors, paths = anyio.run(scenario)

    assert files_seen == 1
    assert files_indexed == 1
    assert errors == ()
    assert paths == ["Contexts/Projects/Canonical Winner.md"]


def test_obsidian_reindex_reports_skip_reasons_and_late_edge_resolution(
    tmp_path: Path,
) -> None:
    """Reindex counts should explain skips and late graph target repairs."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            root = tmp_path / "vault" / "Alexandria" / "Indexes"
            root.mkdir(parents=True)
            (root / "A Owner.md").write_text(
                "---\n"
                "alexandria_type: job_plan\n"
                "id: owner-late-edge\n"
                "title: A Owner\n"
                "status: active\n"
                "---\n\n"
                "# A Owner\n\n[[Alexandria/Indexes/Z Target.md]]\n",
                encoding="utf-8",
            )
            (root / "Z Target.md").write_text(
                "---\n"
                "alexandria_type: job_plan\n"
                "id: target-late-edge\n"
                "title: Z Target\n"
                "status: active\n"
                "---\n\n# Z Target\n",
                encoding="utf-8",
            )
            (root / "Unmanaged.md").write_text(
                "# Unmanaged\n\nNo Alexandria frontmatter.\n",
                encoding="utf-8",
            )

            result = await service.reindex()
        finally:
            await session.close()
            await database.shutdown()

        assert result.files_seen == 3
        assert result.files_indexed == 2
        assert result.files_skipped == 1
        assert result.skip_reasons == {"missing_alexandria_frontmatter": 1}
        assert result.edge_targets_resolved == 1

    anyio.run(scenario)


def test_obsidian_reindex_discards_missing_note_indexes(tmp_path: Path) -> None:
    """Missing Markdown should leave no searchable or stale derived rows."""

    async def scenario() -> tuple[list[str], int, int]:
        database, session, service = await _service(tmp_path)
        try:
            note = await service.save_note(
                ObsidianSaveNote(
                    title="Temporary stale context",
                    body="# Temporary stale context\n\nstale search marker",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_temporary_stale",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            (tmp_path / "vault" / note.relative_path).unlink()
            reindex = await service.reindex()
            hits = await service.search(
                ObsidianSearchQuery(
                    query="stale search marker",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                ),
                refresh=False,
            )
            status = await service.status()
        finally:
            await session.close()
            await database.shutdown()

        return (
            [hit.note.relative_path for hit in hits],
            reindex.stale_marked,
            status.stale_notes,
        )

    assert anyio.run(scenario) == ([], 1, 0)


def test_obsidian_search_filters_stale_notes_before_fts_limit(
    tmp_path: Path,
) -> None:
    """Stale FTS rows should not crowd indexed notes out of limited searches."""

    async def scenario() -> list[str]:
        database, session, service = await _service(tmp_path)
        try:
            stale_paths: list[str] = []
            for index in range(3):
                note = await service.save_note(
                    ObsidianSaveNote(
                        title=f"Temporary stale context {index}",
                        body=(
                            f"# Temporary stale context {index}\n\n"
                            "crowdouttoken crowdouttoken crowdouttoken"
                        ),
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        note_id=f"ctx_stale_crowdout_{index}",
                        frontmatter={"scope": "GLOBAL"},
                    )
                )
                stale_paths.append(note.relative_path)
            await service.save_note(
                ObsidianSaveNote(
                    title="Durable context kept",
                    body="# Durable context kept\n\ncrowdouttoken",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_durable_crowdout",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            for relative_path in stale_paths:
                (tmp_path / "vault" / relative_path).unlink()
            await service.reindex()
            hits = await service.search(
                ObsidianSearchQuery(query="crowdouttoken", limit=1),
                refresh=False,
            )
        finally:
            await session.close()
            await database.shutdown()

        return [hit.note.note_id for hit in hits]

    assert anyio.run(scenario) == ["ctx_durable_crowdout"]


def test_obsidian_fts_search_does_not_select_embedding_column(
    tmp_path: Path,
) -> None:
    """FTS search should hydrate only chunk fields required for its response."""

    async def scenario() -> tuple[list[str], list[str], tuple[str, ...]]:
        database, session, service = await _service(tmp_path)
        statements: list[str] = []

        def capture_statement(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            statements.append(statement)

        try:
            note_id = "ctx_fts_projection"
            await service.save_note(
                ObsidianSaveNote(
                    title="FTS projection",
                    body="# FTS projection\n\nprojectionguardtoken",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id=note_id,
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            event.listen(
                database.engine.sync_engine,
                "before_cursor_execute",
                capture_statement,
            )
            hits = await service.search(
                ObsidianSearchQuery(query="projectionguardtoken", limit=1),
                refresh=False,
            )
        finally:
            event.remove(
                database.engine.sync_engine,
                "before_cursor_execute",
                capture_statement,
            )
            await session.close()
            await database.shutdown()

        return (
            [hit.note.note_id for hit in hits],
            [hit.excerpt for hit in hits],
            tuple(statements),
        )

    note_ids, excerpts, statements = anyio.run(scenario)

    assert note_ids == ["ctx_fts_projection"]
    assert excerpts == ["# FTS projection projectionguardtoken"]
    chunk_selects = tuple(
        statement
        for statement in statements
        if "FROM obsidian_chunks" in statement
        and statement.lstrip().startswith("SELECT")
    )
    assert chunk_selects
    assert all(
        "obsidian_chunks.embedding" not in statement for statement in chunk_selects
    )


def test_obsidian_reindex_triggers_embedding_reindex_when_hook_is_configured(
    tmp_path: Path,
) -> None:
    """Reindex should trigger embedding backfill after vault index rebuild."""

    async def scenario() -> tuple[bool, int]:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            service = ObsidianService(
                repository=repository,
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_hook=lambda: None,
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            note_path = tmp_path / "vault" / "Alexandria" / "Contexts" / "Decisions"
            note_path.mkdir(parents=True, exist_ok=True)
            (note_path / "Reindex.md").write_text(
                "---\n"
                "alexandria_type: context\n"
                "id: ctx_reindex\n"
                "title: Reindex Hook\n"
                "tags:\n"
                "  - obsidian\n"
                "status: active\n"
                "source: human\n"
                "project: heterarchy-alexandria\n"
                "---\n\n"
                "# Reindex Hook\n\nTrigger embedding reindex.\n",
                encoding="utf-8",
            )

            called = False

            async def hook() -> None:
                nonlocal called
                called = True

            service = ObsidianService(
                repository=repository,
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_hook=hook,
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            result = await service.reindex()
        finally:
            await session.close()
            await database.shutdown()

        return called, result.files_indexed

    called, files_indexed = anyio.run(scenario)

    assert called is True
    assert files_indexed == 1


def test_obsidian_reindex_handles_note_id_change_for_same_path(
    tmp_path: Path,
) -> None:
    """Reindex should replace stale path rows when frontmatter id changes."""

    async def scenario() -> tuple[int, int, str, bool]:
        database, session, service = await _service(tmp_path)
        try:
            notes_dir = tmp_path / "vault" / "Alexandria" / "Contexts" / "Decisions"
            notes_dir.mkdir(parents=True)
            note_path = notes_dir / "Storage.md"
            note_path.write_text(
                "---\n"
                "alexandria_type: context\n"
                "id: ctx_storage_old\n"
                "title: Obsidian Storage\n"
                "tags:\n"
                "  - obsidian\n"
                "status: active\n"
                "source: human\n"
                "project: heterarchy-alexandria\n"
                "---\n\n"
                "# Obsidian Storage\n\nOriginal id.\n",
                encoding="utf-8",
            )
            first = await service.reindex()
            note_path.write_text(
                "---\n"
                "alexandria_type: context\n"
                "id: ctx_storage_new\n"
                "title: Obsidian Storage\n"
                "tags:\n"
                "  - obsidian\n"
                "status: active\n"
                "source: human\n"
                "project: heterarchy-alexandria\n"
                "---\n\n"
                "# Obsidian Storage\n\nRenamed id.\n",
                encoding="utf-8",
            )
            second = await service.reindex()
            renamed = await service.read_note("ctx_storage_new")
            try:
                await service.read_note("ctx_storage_old")
            except ObsidianNotFoundError:
                old_id_missing = True
            else:
                old_id_missing = False
        finally:
            await session.close()
            await database.shutdown()
        return first.files_indexed, second.files_indexed, renamed.body, old_id_missing

    first_indexed, second_indexed, body, old_id_missing = anyio.run(scenario)

    assert first_indexed == 1
    assert second_indexed == 1
    assert "Renamed id." in body
    assert old_id_missing is True


def test_obsidian_reindex_reads_existing_embeddings_before_file_row_flush(
    tmp_path: Path,
) -> None:
    """Replacing chunks should not autoflush dirty file metadata before reads."""

    def payload(*, title: str, content_hash: str) -> ObsidianNoteIndex:
        return ObsidianNoteIndex(
            note_id="autoflush-note",
            relative_path="Alexandria/Notes/Autoflush.md",
            alexandria_type=AlexandriaNoteType.CONTEXT,
            title=title,
            status="active",
            tags=["postgresql"],
            project="heterarchy-alexandria",
            source="test",
            content_hash=content_hash,
            frontmatter={"id": "autoflush-note", "title": title},
            body=f"# {title}\n\nBody",
            size_bytes=42,
            modified_at=datetime.now(UTC),
            chunks=[
                ObsidianChunkIndex(
                    chunk_index=0,
                    heading_path=None,
                    text=f"{title} body",
                    content_hash=content_hash,
                    token_count=2,
                )
            ],
        )

    async def scenario() -> list[str]:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        statements: list[str] = []

        def record_statement(
            _connection, _cursor, statement, _parameters, *_args
        ) -> None:
            normalized = " ".join(str(statement).lower().split())
            if normalized.startswith("select obsidian_chunks"):
                statements.append("select_chunks")
            if normalized.startswith("update obsidian_files"):
                statements.append("update_file")

        event.listen(
            database.engine.sync_engine, "before_cursor_execute", record_statement
        )
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            await repository.upsert_note(
                payload(title="Initial", content_hash="hash-a")
            )
            await session.commit()
            statements.clear()

            await repository.upsert_note(
                payload(title="Updated", content_hash="hash-b")
            )
            await session.commit()
            return statements
        finally:
            event.remove(
                database.engine.sync_engine, "before_cursor_execute", record_statement
            )
            await session.close()
            await database.shutdown()

    statements = anyio.run(scenario)

    assert "select_chunks" in statements
    assert "update_file" in statements
    assert statements.index("select_chunks") < statements.index("update_file")


def test_obsidian_reindex_reports_malformed_notes_and_continues(tmp_path: Path) -> None:
    """Malformed managed files must be observable without blocking valid notes."""

    async def scenario() -> tuple[int, list[str]]:
        database, session, service = await _service(tmp_path)
        root = tmp_path / "vault" / "Alexandria" / "Contexts" / "Projects"
        root.mkdir(parents=True)
        (root / "A Unterminated.md").write_text(
            "---\nid: ctx_unterminated\nalexandria_type: context\n",
            encoding="utf-8",
        )
        (root / "B Missing Id.md").write_text(
            "---\nalexandria_type: context\nscope: PROJECT\nproject: project-a\n"
            "---\n\n# Missing Id",
            encoding="utf-8",
        )
        (root / "C Valid.md").write_text(
            "---\nid: ctx_valid\nalexandria_type: context\nscope: PROJECT\n"
            "project: project-a\nstatus: current\n---\n\n# Valid",
            encoding="utf-8",
        )
        try:
            result = await service.reindex()
        finally:
            await session.close()
            await database.shutdown()
        return result.files_indexed, [item.error_code for item in result.error_details]

    files_indexed, error_codes = anyio.run(scenario)

    assert files_indexed == 1
    assert error_codes == ["FRONTMATTER_PARSE_ERROR", "FRONTMATTER_PARSE_ERROR"]


def test_obsidian_reindex_rejects_duplicate_context_content(tmp_path: Path) -> None:
    """Rebuild must apply the same canonical body-signature dedupe as save."""

    async def scenario() -> tuple[int, list[str]]:
        database, session, service = await _service(tmp_path)
        root = tmp_path / "vault" / "Alexandria" / "Contexts" / "Projects"
        root.mkdir(parents=True)
        for note_id, title in (("ctx_first", "A First"), ("ctx_second", "B Second")):
            (root / f"{title}.md").write_text(
                "---\n"
                f"id: {note_id}\n"
                "alexandria_type: context\n"
                f"title: {title}\n"
                "scope: PROJECT\nproject: project-a\nstatus: current\n"
                "---\n\n# Shared\n\nidentical canonical body",
                encoding="utf-8",
            )
        try:
            result = await service.reindex()
        finally:
            await session.close()
            await database.shutdown()
        return result.files_indexed, [item.error_code for item in result.error_details]

    files_indexed, error_codes = anyio.run(scenario)

    assert files_indexed == 1
    assert error_codes == ["DUPLICATE_CONTEXT_CONTENT"]


def test_obsidian_reindex_rejects_missing_supersede_target(tmp_path: Path) -> None:
    """Rebuild must not expose a replacement whose target is absent."""

    async def scenario() -> tuple[int, list[str]]:
        database, session, service = await _service(tmp_path)
        root = tmp_path / "vault" / "Alexandria" / "Contexts" / "Projects"
        root.mkdir(parents=True)
        (root / "Replacement.md").write_text(
            "---\nid: ctx_replacement\nalexandria_type: context\n"
            "scope: PROJECT\nproject: project-a\nstatus: current\n"
            "supersedes_context_id: ctx_absent\n---\n\n# Replacement",
            encoding="utf-8",
        )
        try:
            result = await service.reindex()
        finally:
            await session.close()
            await database.shutdown()
        return result.files_indexed, [item.error_code for item in result.error_details]

    files_indexed, error_codes = anyio.run(scenario)

    assert files_indexed == 0
    assert error_codes == ["INVALID_SUPERSEDE"]


def test_obsidian_reindex_continues_after_one_index_write_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """One PostgreSQL write failure must not hide later valid canonical notes."""

    async def scenario() -> tuple[int, list[str], str]:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        repository = SqlAlchemyObsidianIndexRepository(session=session)
        service = ObsidianService(
            repository=repository,
            vault_path=str(tmp_path / "vault"),
            alexandria_root="Alexandria",
            context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
        )
        root = tmp_path / "vault" / "Alexandria" / "Contexts" / "Projects"
        root.mkdir(parents=True)
        for note_id, title in (("ctx_fail", "A Fail"), ("ctx_valid", "B Valid")):
            (root / f"{title}.md").write_text(
                "---\n"
                f"id: {note_id}\n"
                "alexandria_type: context\n"
                "scope: PROJECT\nproject: project-a\nstatus: current\n"
                f"---\n\n# {title}",
                encoding="utf-8",
            )
        original_upsert = repository.upsert_note

        async def fail_one(payload: ObsidianNoteIndex):
            if payload.note_id == "ctx_fail":
                raise ObsidianIndexWriteError("synthetic per-note failure")
            return await original_upsert(payload)

        monkeypatch.setattr(repository, "upsert_note", fail_one)
        try:
            result = await service.reindex()
            valid = await service.read_note("ctx_valid")
        finally:
            await session.close()
            await database.shutdown()
        return (
            result.files_indexed,
            [item.error_code for item in result.error_details],
            valid.note_id,
        )

    files_indexed, error_codes, valid_id = anyio.run(scenario)

    assert files_indexed == 1
    assert error_codes == ["INDEX_WRITE_FAILED"]
    assert valid_id == "ctx_valid"


def test_obsidian_reindex_classifies_source_read_failure_separately(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Canonical source I/O failures must not be reported as index writes."""

    async def scenario() -> tuple[int, list[str], list[str], str]:
        database, session, service = await _service(tmp_path)
        root = tmp_path / "vault" / "Alexandria" / "Contexts" / "Projects"
        root.mkdir(parents=True)
        for note_id, title in (
            ("ctx_unavailable", "A Unavailable"),
            ("ctx_valid", "B Valid"),
        ):
            (root / f"{title}.md").write_text(
                "---\n"
                f"id: {note_id}\n"
                "alexandria_type: context\n"
                "scope: PROJECT\nproject: project-a\nstatus: current\n"
                f"---\n\n# {title}",
                encoding="utf-8",
            )
        original_indexer = obsidian_vault_lifecycle_service.note_index_from_path

        def fail_one(path: Path, relative_path: str, alexandria_root: str):
            if path.name == "A Unavailable.md":
                raise OSError(35, "Resource deadlock avoided")
            return original_indexer(path, relative_path, alexandria_root)

        monkeypatch.setattr(
            obsidian_vault_lifecycle_service,
            "note_index_from_path",
            fail_one,
        )
        try:
            result = await service.reindex()
            valid = await service.read_note("ctx_valid")
        finally:
            await session.close()
            await database.shutdown()
        return (
            result.files_indexed,
            [item.error_code for item in result.error_details],
            [item.error_message for item in result.error_details],
            valid.note_id,
        )

    files_indexed, error_codes, error_messages, valid_id = anyio.run(scenario)

    assert files_indexed == 1
    assert error_codes == ["SOURCE_READ_FAILED"]
    assert error_messages == ["Canonical Markdown source could not be read"]
    assert valid_id == "ctx_valid"


def test_obsidian_reindex_clears_prior_read_error_for_unmanaged_markdown(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A readable unmanaged file must not retain an earlier source-read error."""

    async def scenario() -> tuple[int, int, int, dict[str, int]]:
        database, session, service = await _service(tmp_path)
        root = tmp_path / "vault" / "Alexandria" / "Indexes"
        root.mkdir(parents=True)
        unmanaged_path = root / "Unmanaged.md"
        unmanaged_path.write_text(
            "# Unmanaged\n\nNo Alexandria frontmatter.\n",
            encoding="utf-8",
        )
        original_indexer = obsidian_vault_lifecycle_service.note_index_from_path

        def fail_read(path: Path, relative_path: str, alexandria_root: str):
            raise OSError(35, "Resource deadlock avoided")

        monkeypatch.setattr(
            obsidian_vault_lifecycle_service,
            "note_index_from_path",
            fail_read,
        )
        try:
            failed = await service.reindex()
            failed_status = await service.status()
            monkeypatch.setattr(
                obsidian_vault_lifecycle_service,
                "note_index_from_path",
                original_indexer,
            )
            recovered = await service.reindex()
            recovered_status = await service.status()
        finally:
            await session.close()
            await database.shutdown()
        return (
            len(failed.error_details),
            failed_status.error_notes,
            recovered_status.error_notes,
            recovered.skip_reasons,
        )

    failed_errors, failed_error_notes, recovered_error_notes, skip_reasons = anyio.run(
        scenario
    )

    assert failed_errors == 1
    assert failed_error_notes == 1
    assert recovered_error_notes == 0
    assert skip_reasons == {"missing_alexandria_frontmatter": 1}


def test_obsidian_reindex_heals_interrupted_supersede(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Canonical replacement survives a failed backlink write and heals on rebuild."""

    async def scenario() -> tuple[str, int, list[str], str, str]:
        database, session, service = await _service(tmp_path)
        try:
            original = await service.save_note(
                ObsidianSaveNote(
                    title="Original",
                    body="# Original\n\ninterrupted lifecycle original",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_interrupted_original",
                    status="current",
                    project="project-a",
                    frontmatter={"scope": "PROJECT"},
                )
            )

            async def fail_backlink(
                *,
                superseded_context_id: str,
                replacement_context_id: str,
            ) -> None:
                assert superseded_context_id == original.note_id
                assert replacement_context_id == "ctx_interrupted_replacement"
                raise OSError("synthetic canonical backlink failure")

            monkeypatch.setattr(service, "_mark_context_superseded", fail_backlink)
            error = ""
            try:
                await service.save_note(
                    ObsidianSaveNote(
                        title="Replacement",
                        body="# Replacement\n\ninterrupted lifecycle replacement",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        note_id="ctx_interrupted_replacement",
                        status="current",
                        project="project-a",
                        frontmatter={
                            "scope": "PROJECT",
                            "supersedes_context_id": original.note_id,
                        },
                    )
                )
            except ObsidianValidationError as exc:
                error = str(exc)
            failed_status = await service.status()
            monkeypatch.undo()
            rebuilt = await service.reindex()
            original_after = await service.read_note(original.note_id)
            replacement_after = await service.read_note("ctx_interrupted_replacement")
        finally:
            await session.close()
            await database.shutdown()
        return (
            error,
            failed_status.error_notes,
            rebuilt.errors,
            original_after.status,
            replacement_after.status,
        )

    error, failed_errors, rebuild_errors, old_status, new_status = anyio.run(scenario)

    assert "INDEX_WRITE_FAILED" in error
    assert failed_errors == 1
    assert rebuild_errors == ()
    assert old_status == "superseded"
    assert new_status == "current"


def test_index_error_persistence_failure_does_not_mask_primary_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A secondary diagnostic write must not replace the canonical save error."""

    async def scenario() -> tuple[str, bool]:
        database, session, service = await _service(tmp_path)
        repository = service._repository

        async def fail_upsert(_payload: ObsidianNoteIndex):
            raise ObsidianIndexWriteError("synthetic primary index failure")

        async def fail_error_record(_error) -> None:
            raise RuntimeError("synthetic diagnostic persistence failure")

        monkeypatch.setattr(repository, "upsert_note", fail_upsert)
        monkeypatch.setattr(repository, "record_index_error", fail_error_record)
        path = "Alexandria/Contexts/Projects/Preserved.md"
        absolute_path = tmp_path / "vault" / path
        try:
            error = ""
            try:
                await service.save_note(
                    ObsidianSaveNote(
                        title="Preserved",
                        body="# Preserved\n",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        note_id="ctx_preserved",
                        relative_path=path,
                        project="project-a",
                        frontmatter={"scope": "PROJECT"},
                    )
                )
            except ObsidianValidationError as exc:
                error = str(exc)
            return error, absolute_path.exists()
        finally:
            await session.close()
            await database.shutdown()

    caplog.set_level("ERROR")
    error, markdown_exists = anyio.run(scenario)

    assert error == "INDEX_WRITE_FAILED: canonical Markdown was preserved for reindex"
    assert markdown_exists is True
    assert "failed to persist Obsidian index error" in caplog.text


def test_obsidian_save_note_writes_markdown_and_reindexes(tmp_path: Path) -> None:
    """Saving a note should write canonical Markdown and make it searchable."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            saved = await service.save_note(
                ObsidianSaveNote(
                    title="Web Research Skill",
                    body="# Web Research Skill\n\nSearch official sources before answering.",
                    alexandria_type=AlexandriaNoteType.SKILL,
                    note_id="skill_web_research",
                    tags=["research", "web-search"],
                    project="heterarchy-alexandria",
                    source="human",
                )
            )
            hits = await service.search(
                ObsidianSearchQuery(
                    query="official sources",
                    alexandria_type=AlexandriaNoteType.SKILL,
                ),
                refresh=False,
            )
        finally:
            await session.close()
            await database.shutdown()

        note_path = tmp_path / "vault" / saved.relative_path
        assert note_path.exists()
        assert saved.relative_path == "Alexandria/Skills/Drafts/Web Research Skill.md"
        assert hits[0].note.note_id == "skill_web_research"

    anyio.run(scenario)


def test_obsidian_save_rejects_stale_agent_update(tmp_path: Path) -> None:
    """Only the first agent holding a matching content hash may replace a note."""

    async def scenario() -> tuple[str, str]:
        database, session, service = await _service(tmp_path)
        try:
            original = await service.save_note(
                ObsidianSaveNote(
                    title="Shared",
                    body="# Shared\n\noriginal",
                    alexandria_type=AlexandriaNoteType.SKILL,
                    note_id="skill_shared_cas",
                )
            )
            first = await service.save_note(
                ObsidianSaveNote(
                    title="Shared",
                    body="# Shared\n\nagent one",
                    alexandria_type=AlexandriaNoteType.SKILL,
                    note_id=original.note_id,
                    relative_path=original.relative_path,
                    expected_content_hash=original.content_hash,
                )
            )
            with pytest.raises(
                ObsidianWriteConflictError,
                match="OBSIDIAN_WRITE_CONFLICT",
            ):
                await service.save_note(
                    ObsidianSaveNote(
                        title="Shared",
                        body="# Shared\n\nagent two",
                        alexandria_type=AlexandriaNoteType.SKILL,
                        note_id=original.note_id,
                        relative_path=original.relative_path,
                        expected_content_hash=original.content_hash,
                    )
                )
            retained = await service.read_note(original.note_id)
            return first.content_hash, retained.body
        finally:
            await session.close()
            await database.shutdown()

    first_hash, retained_body = anyio.run(scenario)

    assert first_hash
    assert "agent one" in retained_body
    assert "agent two" not in retained_body


def test_obsidian_save_rejects_cross_type_note_id_collision(tmp_path: Path) -> None:
    """A non-Context save must never replace an indexed canonical Context ID."""

    async def scenario() -> tuple[str, str, bool]:
        database, session, service = await _service(tmp_path)
        try:
            original = await service.save_note(
                ObsidianSaveNote(
                    title="Stable Context",
                    body="# Stable\n\ncross-type collision guard",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="shared_stable_id",
                    project="project-a",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            error = ""
            try:
                await service.save_note(
                    ObsidianSaveNote(
                        title="Colliding Skill",
                        body="# Skill\n\nmust not replace Context",
                        alexandria_type=AlexandriaNoteType.SKILL,
                        note_id=original.note_id,
                    )
                )
            except ObsidianValidationError as exc:
                error = str(exc)
            retained = await service.read_note(original.note_id)
            skill_path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Skills"
                / "Drafts"
                / "Colliding Skill.md"
            )
        finally:
            await session.close()
            await database.shutdown()
        return error, retained.alexandria_type.value, skill_path.exists()

    error, retained_type, skill_file_exists = anyio.run(scenario)

    assert "DUPLICATE_CONTEXT_ID" in error
    assert retained_type == "context"
    assert skill_file_exists is False


def test_obsidian_save_rejects_dangling_superseded_by_reference(
    tmp_path: Path,
) -> None:
    """A canonical backlink must reference a reciprocal replacement Context."""

    async def scenario() -> tuple[str, bool]:
        database, session, service = await _service(tmp_path)
        try:
            error = ""
            try:
                await service.save_note(
                    ObsidianSaveNote(
                        title="Dangling Backlink",
                        body="# Dangling\n\ninvalid replacement backlink",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        note_id="ctx_dangling_backlink",
                        status="superseded",
                        project="project-a",
                        frontmatter={
                            "scope": "PROJECT",
                            "superseded_by_context_id": "ctx_missing_replacement",
                        },
                    )
                )
            except ObsidianValidationError as exc:
                error = str(exc)
            path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / "Dangling Backlink.md"
            )
        finally:
            await session.close()
            await database.shutdown()
        return error, path.exists()

    error, file_exists = anyio.run(scenario)

    assert "INVALID_SUPERSEDE" in error
    assert file_exists is False


def test_obsidian_context_save_scope_validation_returns_422(tmp_path: Path) -> None:
    """Context identity violations must use the API validation status contract."""
    del tmp_path
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/obsidian/notes",
            json={
                "title": "Invalid Agent Context",
                "body": "# Invalid\n\nagent_id is intentionally absent",
                "alexandria_type": "context",
                "project": "project-a",
                "frontmatter": {"scope": "AGENT"},
            },
        )

    assert response.status_code == 422


def test_explicit_note_routes_return_outcome_and_structured_conflict(
    tmp_path: Path,
) -> None:
    """HTTP callers should receive stage visibility and machine-readable conflicts."""
    del tmp_path

    first_request = {
        "title": "Route First",
        "body": "# Route First\n\nretained",
        "alexandria_type": "skill",
        "id": "skill_route_first",
        "path": "Alexandria/Skills/Drafts/route-first.md",
        "match_by": "path",
    }
    second_request = {
        "title": "Route Second",
        "body": "# Route Second\n\nretained",
        "alexandria_type": "skill",
        "id": "skill_route_second",
        "path": "Alexandria/Skills/Drafts/route-second.md",
        "match_by": "path",
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post("/obsidian/notes/create", json=first_request)
        updated_by_id = client.post(
            "/obsidian/notes/update",
            json={
                **first_request,
                "body": "# Route First\n\nupdated by id",
                "path": None,
                "match_by": "note_id",
            },
        )
        second = client.post("/obsidian/notes/create", json=second_request)
        conflict = client.post(
            "/obsidian/notes/update",
            json={
                **first_request,
                "title": "Ambiguous Route Update",
                "body": "# Ambiguous\n\nnot written",
                "path": second_request["path"],
                "match_by": "note_id",
            },
        )

    assert created.status_code == 201
    assert second.status_code == 201
    assert updated_by_id.status_code == 200
    assert updated_by_id.json()["operation"] == "updated"
    assert created.json()["operation"] == "created"
    assert created.json()["pipeline"]["metadata_status"] == "indexed"
    assert created.json()["pipeline"]["graph_projection_status"] == "stale"
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "error_code": "IDENTITY_CONFLICT",
        "operation": "update",
        "requested_note_id": "skill_route_first",
        "requested_path": "Alexandria/Skills/Drafts/route-second.md",
        "id_target_path": "Alexandria/Skills/Drafts/route-first.md",
        "path_target_id": "skill_route_second",
        "mutation_performed": False,
        "recommended_operation": "resolve_identity",
    }


def test_obsidian_vault_settings_update_redirects_future_writes(
    tmp_path: Path,
) -> None:
    """Runtime vault settings should persist and move future note writes."""

    async def scenario() -> tuple[str, str, bool, bool, str | None]:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        config_path = tmp_path / "vault-config.json"
        target_vault = tmp_path / "Desktop" / "Alexandria"
        store = ObsidianVaultConfigStore(
            default_vault_path=str(tmp_path / "generated-vault"),
            default_alexandria_root="Alexandria",
            config_path=str(config_path),
        )
        service = ObsidianService(
            repository=SqlAlchemyObsidianIndexRepository(session=session),
            vault_config_store=store,
            context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
        )
        try:
            status = await service.configure_vault_settings(
                ObsidianVaultSettingsUpdate(
                    vault_path=str(target_vault),
                    alexandria_root=".",
                    initialize=True,
                    reindex=True,
                )
            )
            saved = await service.save_note(
                ObsidianSaveNote(
                    title="Configured Vault Note",
                    body="# Configured Vault Note\n\nSaved from plugin settings.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_configured_vault_note",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            persisted = loads_json(config_path.read_bytes())
            persisted_path = (
                persisted["vault_path"] if isinstance(persisted, dict) else None
            )
        finally:
            await session.close()
            await database.shutdown()
        return (
            status.vault_path,
            status.alexandria_root,
            (target_vault / "START_HERE.md").exists(),
            (target_vault / saved.relative_path).exists(),
            persisted_path if isinstance(persisted_path, str) else None,
        )

    status_path, alexandria_root, start_exists, note_exists, persisted_path = anyio.run(
        scenario
    )

    assert status_path == str((tmp_path / "Desktop" / "Alexandria").resolve())
    assert alexandria_root == "."
    assert start_exists is True
    assert note_exists is True
    assert persisted_path == status_path


def test_obsidian_roundtrips_memory_skill_prompt_after_postgres_rebuild(
    tmp_path: Path,
) -> None:
    """Canonical artifact notes should survive PostgreSQL index deletion and rebuild."""

    async def scenario() -> None:
        vault_path = tmp_path / "vault"
        memory_service = MemoryCompactService(
            repository=ObsidianMemoryCompactRepository(
                vault_path=vault_path,
                relative_dir="Alexandria/Memory Compacts",
            )
        )
        compact = await memory_service.create(
            MemoryCompactCreate(
                project="heterarchy-alexandria",
                covered_from=datetime(2026, 5, 25, tzinfo=UTC),
                covered_to=datetime(2026, 5, 26, tzinfo=UTC),
                markdown_body=(
                    "## Durable Decisions\n"
                    "- Obsidian remains canonical memory.\n\n"
                    "## Current State\n"
                    "- Obsidian canonical memory survives PostgreSQL index rebuild.\n\n"
                    "## Risks and Blockers\n"
                    "- None recorded.\n\n"
                    "## Next Actions\n"
                    "- Rebuild the PostgreSQL index as needed.\n\n"
                    "## Coverage\n"
                    "- covered_from: 2026-05-25T00:00:00+00:00\n"
                    "- covered_to: 2026-05-26T00:00:00+00:00\n"
                    "- project: heterarchy-alexandria\n\n"
                    "## Evidence Summary\n"
                    "- Storage decision source ref."
                ),
                status=MemoryCompactStatus.CURRENT,
                source_refs=[
                    MemoryCompactSourceRefCreate(
                        source_type="context",
                        source_id="ctx-storage",
                        title="Storage decision",
                        detail_path="Alexandria/Contexts/Decisions/Storage.md",
                    )
                ],
            )
        )

        first_database = Database(
            database_url=_database_url(),
            create_schema=True,
        )
        await first_database.initialize()
        first_session = first_database.session()
        try:
            first_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=first_session),
                vault_path=str(vault_path),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            skill = await first_service.save_note(
                ObsidianSaveNote(
                    title="Browser Verification Skill",
                    body=(
                        "# Browser Verification Skill\n\n"
                        "Use deterministic browser checks and bounded waits."
                    ),
                    alexandria_type=AlexandriaNoteType.SKILL,
                    note_id="skill_browser_verification",
                    project="heterarchy-alexandria",
                    tags=["skill", "verification"],
                    source="import",
                    frontmatter={
                        "artifact_kind": "skill",
                        "skill_status": "draft",
                    },
                )
            )
            prompt = await first_service.save_note(
                ObsidianSaveNote(
                    title="Release Review Prompt",
                    body=(
                        "# Release Review Prompt\n\n"
                        "Check changelog, tests, and rollback notes before release."
                    ),
                    alexandria_type=AlexandriaNoteType.PROMPT,
                    note_id="prompt_release_review",
                    project="heterarchy-alexandria",
                    tags=["prompt", "release"],
                    source="import",
                    frontmatter={
                        "artifact_kind": "prompt",
                        "prompt_kind": "template",
                    },
                )
            )
        finally:
            await first_session.close()
            await first_database.shutdown()

        rebuild_database = Database(
            database_url=_database_url(),
            create_schema=True,
        )
        await rebuild_database.initialize()
        rebuild_session = rebuild_database.session()
        try:
            rebuilt_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=rebuild_session),
                vault_path=str(vault_path),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            reindex = await rebuilt_service.reindex()
            memory_hits = await rebuilt_service.search(
                ObsidianSearchQuery(
                    query="canonical memory survives",
                    alexandria_type=AlexandriaNoteType.MEMORY_COMPACT,
                    project="heterarchy-alexandria",
                ),
                refresh=False,
            )
            skill_hits = await rebuilt_service.search(
                ObsidianSearchQuery(
                    query="deterministic browser checks",
                    alexandria_type=AlexandriaNoteType.SKILL,
                ),
                refresh=False,
            )
            prompt_hits = await rebuilt_service.search(
                ObsidianSearchQuery(
                    query="rollback notes before release",
                    alexandria_type=AlexandriaNoteType.PROMPT,
                ),
                refresh=False,
            )
            memory_note = await rebuilt_service.read_note_by_path(
                "Alexandria/Memory Compacts/"
                f"{compact.created_at.year:04d}/{compact.created_at.month:02d}/"
                f"{compact.id}.md"
            )
            skill_note = await rebuilt_service.read_note(skill.note_id)
            prompt_note = await rebuilt_service.read_note(prompt.note_id)
        finally:
            await rebuild_session.close()
            await rebuild_database.shutdown()

        assert reindex.files_indexed == 3
        assert memory_hits[0].note.note_id == compact.id
        assert skill_hits[0].note.note_id == "skill_browser_verification"
        assert prompt_hits[0].note.note_id == "prompt_release_review"
        assert memory_note.alexandria_type is AlexandriaNoteType.MEMORY_COMPACT
        assert memory_note.body.startswith("## Durable Decisions")
        assert skill_note.frontmatter["skill_status"] == "draft"
        assert prompt_note.frontmatter["prompt_kind"] == "template"

    anyio.run(scenario)


def test_obsidian_save_existing_default_path_reuses_note_id(tmp_path: Path) -> None:
    """Saving the same generated path twice should update instead of path-conflict."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            first = await service.save_note(
                ObsidianSaveNote(
                    title="Repeatable Smoke",
                    body="# Repeatable Smoke\n\nfirst body",
                    alexandria_type=AlexandriaNoteType.JOB_PLAN,
                    tags=["smoke-test"],
                )
            )
            second = await service.save_note(
                ObsidianSaveNote(
                    title="Repeatable Smoke",
                    body="# Repeatable Smoke\n\nsecond body",
                    alexandria_type=AlexandriaNoteType.JOB_PLAN,
                    tags=["smoke-test"],
                )
            )
        finally:
            await session.close()
            await database.shutdown()

        assert second.note_id == first.note_id
        assert second.relative_path == first.relative_path
        assert "second body" in second.body

    anyio.run(scenario)


def test_explicit_note_write_updates_by_id_and_preserves_history(
    tmp_path: Path,
) -> None:
    """Explicit update-by-id should retain identity and advance server history."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            created = await service.write_note(
                ObsidianWriteNote(
                    write_mode=ObsidianWriteMode.CREATE,
                    match_by=ObsidianWriteMatchBy.PATH,
                    frontmatter_mode=ObsidianFrontmatterMode.MERGE,
                    note=ObsidianSaveNote(
                        title="History Contract",
                        body="# History Contract\n\nfirst",
                        alexandria_type=AlexandriaNoteType.SKILL,
                        note_id="skill_history_contract",
                        relative_path="Alexandria/Skills/Drafts/history-contract.md",
                        source="human",
                        frontmatter={
                            "owner": "library-team",
                            "created_at": "2000-01-01T00:00:00Z",
                            "original_source": "forged",
                            "initial_content_hash": "forged",
                            "version": 99,
                        },
                    ),
                )
            )
            generated_path_peer = await service.save_note(
                ObsidianSaveNote(
                    title="History Contract",
                    body="# Generated Path Peer\n\nmust remain separate",
                    alexandria_type=AlexandriaNoteType.SKILL,
                    note_id="skill_history_generated_peer",
                )
            )
            updated = await service.write_note(
                ObsidianWriteNote(
                    write_mode=ObsidianWriteMode.UPDATE,
                    match_by=ObsidianWriteMatchBy.NOTE_ID,
                    frontmatter_mode=ObsidianFrontmatterMode.MERGE,
                    note=ObsidianSaveNote(
                        title="History Contract",
                        body="# History Contract\n\nsecond",
                        alexandria_type=AlexandriaNoteType.SKILL,
                        note_id=created.note.note_id,
                        source="mcp",
                        frontmatter={"reviewed": True},
                    ),
                )
            )
            unchanged = await service.write_note(
                ObsidianWriteNote(
                    write_mode=ObsidianWriteMode.UPDATE,
                    match_by=ObsidianWriteMatchBy.NOTE_ID,
                    note=ObsidianSaveNote(
                        title="History Contract",
                        body="# History Contract\n\nsecond",
                        alexandria_type=AlexandriaNoteType.SKILL,
                        note_id=created.note.note_id,
                        source="mcp",
                        frontmatter={"reviewed": True},
                    ),
                )
            )
            peer_after = await service.read_note(generated_path_peer.note_id)
        finally:
            await session.close()
            await database.shutdown()

        created_frontmatter = created.note.frontmatter
        updated_frontmatter = updated.note.frontmatter
        assert created.operation is ObsidianWriteOperation.CREATED
        assert created_frontmatter["created_at"] != "2000-01-01T00:00:00Z"
        assert created_frontmatter["original_source"] == "human"
        assert created_frontmatter["initial_content_hash"] != "forged"
        assert created_frontmatter["version"] == 1
        assert updated.operation is ObsidianWriteOperation.UPDATED
        assert unchanged.operation is ObsidianWriteOperation.UNCHANGED
        assert updated.note.note_id == created.note.note_id
        assert updated.note.relative_path == created.note.relative_path
        assert updated_frontmatter["created_at"] == created_frontmatter["created_at"]
        assert updated_frontmatter["original_source"] == "human"
        assert (
            updated_frontmatter["initial_content_hash"]
            == created_frontmatter["initial_content_hash"]
        )
        assert (
            updated_frontmatter["previous_content_hash"]
            == created_frontmatter["content_hash"]
        )
        assert updated_frontmatter["version"] == 2
        assert updated_frontmatter["last_modified_by"] == "mcp"
        assert updated_frontmatter["owner"] == "library-team"
        assert updated_frontmatter["reviewed"] is True
        assert unchanged.note.frontmatter["version"] == 2
        assert unchanged.reindex_required is False
        assert "must remain separate" in peer_after.body

    anyio.run(scenario)


def test_explicit_note_write_rejects_identity_conflict_before_mutation(
    tmp_path: Path,
) -> None:
    """An id and path that select different notes must not mutate either note."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            first = await service.save_note(
                ObsidianSaveNote(
                    title="First Identity",
                    body="# First\n\nretained first",
                    alexandria_type=AlexandriaNoteType.SKILL,
                    note_id="skill_identity_first",
                    relative_path="Alexandria/Skills/Drafts/first.md",
                )
            )
            second = await service.save_note(
                ObsidianSaveNote(
                    title="Second Identity",
                    body="# Second\n\nretained second",
                    alexandria_type=AlexandriaNoteType.SKILL,
                    note_id="skill_identity_second",
                    relative_path="Alexandria/Skills/Drafts/second.md",
                )
            )
            with pytest.raises(ObsidianIdentityConflictError) as caught:
                await service.write_note(
                    ObsidianWriteNote(
                        write_mode=ObsidianWriteMode.UPDATE,
                        match_by=ObsidianWriteMatchBy.NOTE_ID,
                        note=ObsidianSaveNote(
                            title="Ambiguous",
                            body="# Ambiguous\n\nshould never be written",
                            alexandria_type=AlexandriaNoteType.SKILL,
                            note_id=first.note_id,
                            relative_path=second.relative_path,
                        ),
                    )
                )
            first_after = await service.read_note(first.note_id)
            second_after = await service.read_note(second.note_id)
        finally:
            await session.close()
            await database.shutdown()

        detail = caught.value.route_detail()
        assert detail["error_code"] == "IDENTITY_CONFLICT"
        assert detail["mutation_performed"] is False
        assert "retained first" in first_after.body
        assert "retained second" in second_after.body

    anyio.run(scenario)


def test_explicit_update_requires_existing_exact_target(tmp_path: Path) -> None:
    """Update-only mode should return a typed missing-target failure."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            with pytest.raises(ObsidianWriteTargetNotFoundError):
                await service.write_note(
                    ObsidianWriteNote(
                        write_mode=ObsidianWriteMode.UPDATE,
                        match_by=ObsidianWriteMatchBy.NOTE_ID,
                        note=ObsidianSaveNote(
                            title="Missing",
                            body="# Missing\n\nno target",
                            alexandria_type=AlexandriaNoteType.SKILL,
                            note_id="skill_missing_explicit",
                        ),
                    )
                )
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_explicit_update_preserves_omitted_optional_fields(tmp_path: Path) -> None:
    """Presence-aware updates must not replace omitted metadata with API defaults."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            created = await service.save_note(
                ObsidianSaveNote(
                    title="Presence Contract",
                    body="# Presence Contract\n\nfirst",
                    alexandria_type=AlexandriaNoteType.SKILL,
                    note_id="skill_presence_contract",
                    relative_path="Alexandria/Skills/Drafts/presence.md",
                    tags=("keep-me",),
                    status="reviewed",
                    project="heterarchy-alexandria",
                    source="human",
                )
            )
            updated = await service.write_note(
                ObsidianWriteNote(
                    write_mode=ObsidianWriteMode.UPDATE,
                    match_by=ObsidianWriteMatchBy.NOTE_ID,
                    provided_fields=frozenset(
                        {"title", "body", "alexandria_type", "id", "match_by"}
                    ),
                    note=ObsidianSaveNote(
                        title=created.title,
                        body="# Presence Contract\n\nsecond",
                        alexandria_type=created.alexandria_type,
                        note_id=created.note_id,
                    ),
                )
            )
        finally:
            await session.close()
            await database.shutdown()

        assert updated.note.tags == ("keep-me",)
        assert updated.note.status == "reviewed"
        assert updated.note.project == "heterarchy-alexandria"
        assert updated.note.source == "human"

    anyio.run(scenario)


@pytest.mark.parametrize(
    ("match_by", "note_id", "relative_path"),
    [
        (ObsidianWriteMatchBy.NOTE_ID, None, "Alexandria/Skills/no-id.md"),
        (ObsidianWriteMatchBy.PATH, "skill_no_path", None),
    ],
)
def test_explicit_create_requires_its_exact_selector(
    tmp_path: Path,
    match_by: ObsidianWriteMatchBy,
    note_id: str | None,
    relative_path: str | None,
) -> None:
    """Create mode must validate its declared exact selector before mutation."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            with pytest.raises(ObsidianValidationError):
                await service.write_note(
                    ObsidianWriteNote(
                        write_mode=ObsidianWriteMode.CREATE,
                        match_by=match_by,
                        note=ObsidianSaveNote(
                            title="Missing Selector",
                            body="# Missing Selector",
                            alexandria_type=AlexandriaNoteType.SKILL,
                            note_id=note_id,
                            relative_path=relative_path,
                        ),
                    )
                )
            assert not list((tmp_path / "vault").rglob("*.md"))
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_obsidian_read_rejects_indexed_note_missing_frontmatter(tmp_path: Path) -> None:
    """Read should not hide source Markdown corruption behind PostgreSQL index data."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            saved = await service.save_note(
                ObsidianSaveNote(
                    title="Canonical Note",
                    body="# Canonical Note\n\nOriginal source.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_canonical",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            note_path = tmp_path / "vault" / saved.relative_path
            note_path.write_text(
                "# Canonical Note\n\nfrontmatter removed", encoding="utf-8"
            )
            try:
                await service.read_note("ctx_canonical")
            except ObsidianValidationError as exc:
                message = str(exc)
            else:
                message = ""
        finally:
            await session.close()
            await database.shutdown()

        assert "missing Alexandria frontmatter" in message

    anyio.run(scenario)


def test_obsidian_save_note_redacts_secret_like_frontmatter_values(
    tmp_path: Path,
) -> None:
    """Secret-like frontmatter strings should not be written raw."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            saved = await service.save_note(
                ObsidianSaveNote(
                    title="Frontmatter Redaction",
                    body="# Frontmatter Redaction\n\nSafe body.",
                    alexandria_type=AlexandriaNoteType.PROMPT,
                    note_id="prompt_frontmatter_redaction",
                    frontmatter={
                        "prompt_kind": "template",
                        "metadata": {
                            "api_key": "sk-" + ("x" * 60),
                        },
                    },
                )
            )
        finally:
            await session.close()
            await database.shutdown()

        note_text = (tmp_path / "vault" / saved.relative_path).read_text(
            encoding="utf-8"
        )
        assert "sk-" + ("x" * 60) not in note_text
        assert "api_key" not in note_text
        assert "potential secret-like frontmatter field was redacted" in note_text

    anyio.run(scenario)


def test_obsidian_vault_inventory_and_path_search(
    tmp_path: Path,
) -> None:
    """Vault operation inventory should read managed notes without FTS dependency."""

    async def scenario() -> tuple[list[str], list[str], list[str]]:
        database, session, service = await _service(tmp_path)
        try:
            await service.save_note(
                ObsidianSaveNote(
                    title="Loose Project Context",
                    body="# Loose Project Context\n\nInventory marker.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_loose_project_context",
                    relative_path=(
                        "Alexandria/Contexts/Projects/Loose Project Context.md"
                    ),
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            inventory = await service.inventory_vault(
                ObsidianVaultInventoryRequest(scope_path="Alexandria/Contexts/Projects")
            )
            invalid_path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / "Invalid.md"
            )
            invalid_path.write_text("# Missing frontmatter\n", encoding="utf-8")
            managed_paths = await service.managed_markdown_paths()
            matches = await service.search_vault_paths(
                query="Loose Project",
                scope_path="Alexandria/Contexts/Projects",
            )
        finally:
            await session.close()
            await database.shutdown()
        return (
            [item.relative_path for item in inventory],
            [item.note_id for item in matches],
            managed_paths,
        )

    paths, matches, managed_paths = anyio.run(scenario)

    assert paths == ["Alexandria/Contexts/Projects/Loose Project Context.md"]
    assert matches == ["ctx_loose_project_context"]
    assert managed_paths == [
        "Alexandria/Contexts/Projects/Invalid.md",
        "Alexandria/Contexts/Projects/Loose Project Context.md",
    ]


def test_obsidian_vault_inventory_accepts_implementation_history(
    tmp_path: Path,
) -> None:
    """Vault inventory should classify implementation history notes."""

    async def scenario() -> tuple[list[tuple[str, AlexandriaNoteType, str]], list[str]]:
        database, session, service = await _service(tmp_path)
        try:
            history_dir = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / "heterarchy-alexandria"
                / "dev-size"
                / "Implementation History"
            )
            history_dir.mkdir(parents=True)
            (history_dir / "2026-07-17 PRD implementation history.md").write_text(
                "---\n"
                "alexandria_type: implementation_history\n"
                "id: implementation_history_2026_07_17_prd\n"
                "title: 2026-07-17 PRD implementation history\n"
                "project: heterarchy-alexandria\n"
                "status: active\n"
                "---\n\n"
                "# 2026-07-17 PRD implementation history\n\n"
                "[Summarlization]\n"
                "- Memory Compact gate was hardened.\n\n"
                "[본문]\n"
                "- Evidence and validation commands are preserved here.\n",
                encoding="utf-8",
            )
            inventory = await service.inventory_vault(
                ObsidianVaultInventoryRequest(
                    scope_path=(
                        "Alexandria/Contexts/Projects/heterarchy-alexandria/dev-size/"
                        "Implementation History"
                    )
                )
            )
            matches = await service.search_vault_paths(
                query="PRD implementation",
                scope_path=(
                    "Alexandria/Contexts/Projects/heterarchy-alexandria/dev-size/"
                    "Implementation History"
                ),
            )
        finally:
            await session.close()
            await database.shutdown()
        return (
            [
                (item.note_id, item.alexandria_type, item.relative_path)
                for item in inventory
            ],
            [item.note_id for item in matches],
        )

    inventory, matches = anyio.run(scenario)

    assert inventory == [
        (
            "implementation_history_2026_07_17_prd",
            AlexandriaNoteType.IMPLEMENTATION_HISTORY,
            (
                "Alexandria/Contexts/Projects/heterarchy-alexandria/dev-size/"
                "Implementation History/2026-07-17 PRD implementation history.md"
            ),
        )
    ]
    assert matches == ["implementation_history_2026_07_17_prd"]


def test_obsidian_vault_move_plan_blocks_overwrite(
    tmp_path: Path,
) -> None:
    """Dry-run move planning should reject overwrites before mutation."""

    async def scenario() -> tuple[str, str, bool]:
        database, session, service = await _service(tmp_path)
        try:
            source = await service.save_note(
                ObsidianSaveNote(
                    title="Move Source",
                    body="# Move Source\n\nSource body.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_move_source",
                    relative_path="Alexandria/Contexts/Projects/Move Source.md",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            destination = await service.save_note(
                ObsidianSaveNote(
                    title="Move Destination",
                    body="# Move Destination\n\nDestination body.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_move_destination",
                    relative_path=(
                        "Alexandria/Contexts/Projects/organized/Move Source.md"
                    ),
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            plan = await service.plan_vault_moves(
                ObsidianVaultMovePlanRequest(
                    moves=[
                        ObsidianVaultMoveRequest(
                            source_path=source.relative_path,
                            destination_path=destination.relative_path,
                            reason="organize loose note",
                        )
                    ]
                )
            )
            source_exists = (tmp_path / "vault" / source.relative_path).exists()
        finally:
            await session.close()
            await database.shutdown()
        return plan.status, plan.skipped[0].reason, source_exists

    status, skip_reason, source_exists = anyio.run(scenario)

    assert status == "blocked"
    assert skip_reason == "destination_exists"
    assert source_exists is True


def test_obsidian_vault_apply_moves_writes_reports_and_reindexes(
    tmp_path: Path,
) -> None:
    """Applying moves should preserve notes, write reports, and rebuild the index."""

    async def scenario() -> tuple[str, str, str, bool, bool, bool, int]:
        database, session, service = await _service(tmp_path)
        try:
            source = await service.save_note(
                ObsidianSaveNote(
                    title="Apply Source",
                    body="# Apply Source\n\nverification move marker.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_apply_source",
                    relative_path="Alexandria/Contexts/Projects/Apply Source.md",
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            report = await service.apply_vault_moves(
                ObsidianVaultMoveApplyRequest(
                    moves=[
                        ObsidianVaultMoveRequest(
                            source_path=source.relative_path,
                            destination_path=(
                                "Alexandria/Contexts/Projects/organized/Apply Source.md"
                            ),
                            reason="organize loose note",
                        )
                    ],
                    report_path="Alexandria/_Ops/Vault/Reports/apply-source-report",
                    verification_query="verification move marker",
                )
            )
            moved_note = await service.read_note_by_path(
                report.moved[0].destination_path
            )
            report_json = loads_json(
                (tmp_path / "vault" / report.report_json_path).read_bytes()
            )
        finally:
            await session.close()
            await database.shutdown()
        assert isinstance(report_json, dict)
        return (
            report.status,
            moved_note.note_id,
            report.verification.reindex_status,
            report.hard_delete_performed,
            (tmp_path / "vault" / source.relative_path).exists(),
            (tmp_path / "vault" / report.report_markdown_path).exists(),
            int(report_json["verification"]["verification_hits"]),
        )

    (
        status,
        note_id,
        reindex_status,
        hard_delete_performed,
        source_exists,
        markdown_report_exists,
        verification_hits,
    ) = anyio.run(scenario)

    assert status == "succeeded"
    assert note_id == "ctx_apply_source"
    assert reindex_status == "succeeded"
    assert hard_delete_performed is False
    assert source_exists is False
    assert markdown_report_exists is True
    assert verification_hits == 1


def test_obsidian_vault_apply_preflights_report_before_moves(
    tmp_path: Path,
) -> None:
    """Report destination conflicts should fail before any vault mutation."""

    async def scenario() -> tuple[bool, bool]:
        database, session, service = await _service(tmp_path)
        try:
            source = await service.save_note(
                ObsidianSaveNote(
                    title="Preflight Source",
                    body="# Preflight Source\n\nmust stay put.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_preflight_source",
                    relative_path=("Alexandria/Contexts/Projects/Preflight Source.md"),
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            report_path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "_Ops"
                / "Vault"
                / "Reports"
                / "preflight-report.md"
            )
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text("existing report", encoding="utf-8")

            try:
                await service.apply_vault_moves(
                    ObsidianVaultMoveApplyRequest(
                        moves=[
                            ObsidianVaultMoveRequest(
                                source_path=source.relative_path,
                                destination_path=(
                                    "Alexandria/Contexts/Projects/organized/"
                                    "Preflight Source.md"
                                ),
                                reason="organize loose note",
                            )
                        ],
                        report_path="Alexandria/_Ops/Vault/Reports/preflight-report",
                    )
                )
            except ObsidianValidationError as exc:
                assert str(exc) == "vault move report destination exists"
            else:
                raise AssertionError("report preflight conflict did not fail")
        finally:
            await session.close()
            await database.shutdown()

        return (
            (tmp_path / "vault" / source.relative_path).exists(),
            (
                tmp_path
                / "vault"
                / "Alexandria/Contexts/Projects/organized/Preflight Source.md"
            ).exists(),
        )

    source_exists, destination_exists = anyio.run(scenario)

    assert source_exists is True
    assert destination_exists is False


def test_obsidian_reindex_accepts_legacy_project_context_type(
    tmp_path: Path,
) -> None:
    """Legacy project-context notes should remain searchable Alexandria sources."""

    async def scenario() -> None:
        database, session, service = await _service(tmp_path)
        try:
            note_path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Project Context"
                / "Legacy Project Context.md"
            )
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(
                "\n".join(
                    [
                        "---",
                        "id: ctx_legacy_project_context",
                        "title: Legacy Project Context",
                        "type: project-context",
                        "project: omx-agent-adapter",
                        "tags:",
                        "  - command-catalog",
                        "---",
                        "",
                        "# Legacy Project Context",
                        "",
                        "command catalog consolidation durable source",
                    ]
                ),
                encoding="utf-8",
            )

            result = await service.reindex()
            response = await service.search(
                ObsidianSearchQuery(
                    query="command catalog consolidation",
                    project="omx-agent-adapter",
                )
            )
        finally:
            await session.close()
            await database.shutdown()

        assert result.errors == ()
        assert [hit.note.note_id for hit in response] == ["ctx_legacy_project_context"]
        assert response[0].note.alexandria_type is AlexandriaNoteType.CONTEXT
        assert response[0].note.frontmatter["alexandria_type"] == "context"

    anyio.run(scenario)
