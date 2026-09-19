"""Canonical Context lifecycle and round-trip regression contracts."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import anyio
from pytest import MonkeyPatch
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.application.integration.obsidian_context_read_mapper import (
    context_record_from_obsidian_note,
)
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.event_enum.context_enums import ContextKind
from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianNoteIndex,
    ObsidianSaveNote,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIndexWriteError,
    ObsidianValidationError,
)
from app.shared.infrastructure.database import Database

NESTED_METADATA = (
    b"custom_metadata:\n"
    b"  owner: alexandria-user\n"
    b"  stages:\n"
    b"    - name: alpha\n"
    b"      flags:\n"
    b"        enabled: true\n"
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


async def _service(tmp_path: Path) -> tuple[Database, AsyncSession, ObsidianService]:
    database = Database(database_url=_database_url(), create_schema=True)
    await database.initialize()
    session = database.session()
    service = ObsidianService(
        repository=SqlAlchemyObsidianIndexRepository(session=session),
        vault_path=str(tmp_path / "vault"),
        alexandria_root="Alexandria",
    )
    return database, session, service


def _context_save(
    note_id: str,
    title: str,
    body: str,
    frontmatter: dict[str, str],
) -> ObsidianSaveNote:
    return ObsidianSaveNote(
        title=title,
        body=body,
        alexandria_type=AlexandriaNoteType.CONTEXT,
        note_id=note_id,
        status="current",
        project="project-a",
        frontmatter={"scope": "PROJECT", **frontmatter},
    )


def _inject_nested_metadata(path: Path) -> None:
    document = path.read_bytes()
    closing_delimiter = document.find(b"---\n", len(b"---\n"))
    assert closing_delimiter > 0
    path.write_bytes(
        document[:closing_delimiter] + NESTED_METADATA + document[closing_delimiter:]
    )


def _write_context(path: Path, note_id: str, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {note_id}\n"
        "alexandria_type: context\n"
        f"title: {title}\n"
        "scope: PROJECT\n"
        "project: project-a\n"
        "status: current\n"
        "---\n\n"
        f"# {title}\n\n{note_id} durable content\n",
        encoding="utf-8",
    )


def test_three_node_supersede_chain_survives_reindex_with_bidirectional_links(
    tmp_path: Path,
) -> None:
    """A<-B<-C must retain both links on B and correct lifecycle states."""

    async def scenario() -> tuple[ObsidianNote, ObsidianNote, ObsidianNote, list[str]]:
        database, session, service = await _service(tmp_path)
        try:
            await service.save_note(
                _context_save("ctx_a", "Context A", "# A\n\nfirst revision", {})
            )
            await service.save_note(
                _context_save(
                    "ctx_b",
                    "Context B",
                    "# B\n\nsecond revision",
                    {"supersedes_context_id": "ctx_a"},
                )
            )
            await service.save_note(
                _context_save(
                    "ctx_c",
                    "Context C",
                    "# C\n\nthird revision",
                    {"supersedes_context_id": "ctx_b"},
                )
            )
            rebuilt = await service.reindex()
            return (
                await service.read_note("ctx_a"),
                await service.read_note("ctx_b"),
                await service.read_note("ctx_c"),
                rebuilt.errors,
            )
        finally:
            await session.close()
            await database.shutdown()

    first, middle, current, errors = anyio.run(scenario)

    assert errors == ()
    assert first.status == "superseded"
    assert first.frontmatter["superseded_by_context_id"] == "ctx_b"
    assert middle.status == "superseded"
    assert middle.frontmatter["supersedes_context_id"] == "ctx_a"
    assert middle.frontmatter["superseded_by_context_id"] == "ctx_c"
    assert current.status == "current"
    assert current.frontmatter["supersedes_context_id"] == "ctx_b"


def test_reindex_quarantines_dangling_superseded_by_as_invalid_supersede(
    tmp_path: Path,
) -> None:
    """A dangling canonical backlink must be isolated with a structured code."""

    async def scenario() -> tuple[int, list[tuple[str, str | None, str]]]:
        database, session, service = await _service(tmp_path)
        path = (
            tmp_path
            / "vault"
            / "Alexandria"
            / "Contexts"
            / "Projects"
            / "Dangling Backlink.md"
        )
        _write_context(path, "ctx_dangling_backlink", "Dangling Backlink")
        text = path.read_text(encoding="utf-8").replace(
            "status: current\n",
            "status: superseded\nsuperseded_by_context_id: ctx_absent\n",
        )
        path.write_text(text, encoding="utf-8")
        try:
            rebuilt = await service.reindex()
            details = [
                (item.error_code, item.context_id, item.note_path)
                for item in rebuilt.error_details
            ]
            return rebuilt.files_indexed, details
        finally:
            await session.close()
            await database.shutdown()

    indexed, details = anyio.run(scenario)

    assert indexed == 0
    assert details == [
        (
            "INVALID_SUPERSEDE",
            "ctx_dangling_backlink",
            "Alexandria/Contexts/Projects/Dangling Backlink.md",
        )
    ]


def test_archive_preserves_nested_unknown_yaml_bytes(tmp_path: Path) -> None:
    """Archiving may patch owned scalars but must not rewrite unknown YAML."""

    async def scenario() -> bytes:
        database, session, service = await _service(tmp_path)
        try:
            saved = await service.save_note(
                _context_save(
                    "ctx_archive_metadata",
                    "Archive Metadata",
                    "# Archive\n\nunknown metadata contract",
                    {},
                )
            )
            path = tmp_path / "vault" / saved.relative_path
            _inject_nested_metadata(path)
            await service.reindex()
            await service.archive_context(saved.note_id)
            return path.read_bytes()
        finally:
            await session.close()
            await database.shutdown()

    archived_document = anyio.run(scenario)

    assert NESTED_METADATA in archived_document


def test_supersede_preserves_nested_unknown_yaml_bytes(tmp_path: Path) -> None:
    """Writing a replacement must preserve unknown YAML on the old Context."""

    async def scenario() -> bytes:
        database, session, service = await _service(tmp_path)
        try:
            original = await service.save_note(
                _context_save(
                    "ctx_supersede_metadata",
                    "Supersede Metadata",
                    "# Original\n\nunknown metadata contract",
                    {},
                )
            )
            original_path = tmp_path / "vault" / original.relative_path
            _inject_nested_metadata(original_path)
            await service.reindex()
            await service.save_note(
                _context_save(
                    "ctx_supersede_metadata_replacement",
                    "Supersede Metadata Replacement",
                    "# Replacement\n\nnew canonical revision",
                    {"supersedes_context_id": original.note_id},
                )
            )
            return original_path.read_bytes()
        finally:
            await session.close()
            await database.shutdown()

    superseded_document = anyio.run(scenario)

    assert NESTED_METADATA in superseded_document


def test_explicit_supersede_links_existing_contexts_idempotently(
    tmp_path: Path,
) -> None:
    """Explicit lifecycle linking must preserve content and be retry-safe."""

    async def scenario() -> tuple[
        ObsidianNote,
        ObsidianNote,
        ObsidianNote,
        ObsidianNote,
        list[str],
    ]:
        database, session, service = await _service(tmp_path)
        try:
            original = await service.save_note(
                _context_save(
                    "ctx_explicit_original",
                    "Explicit Original",
                    "# Original\n\noriginal body must remain durable",
                    {},
                )
            )
            replacement = await service.save_note(
                _context_save(
                    "ctx_explicit_replacement",
                    "Explicit Replacement",
                    "# Replacement\n\nreplacement body must remain durable",
                    {},
                )
            )
            first_old, first_new = await service.supersede_context(
                original.note_id,
                replacement.note_id,
            )
            second_old, second_new = await service.supersede_context(
                original.note_id,
                replacement.note_id,
            )
            rebuilt = await service.reindex()
            return first_old, first_new, second_old, second_new, rebuilt.errors
        finally:
            await session.close()
            await database.shutdown()

    first_old, first_new, second_old, second_new, errors = anyio.run(scenario)

    assert errors == ()
    assert first_old.status == "superseded"
    assert first_old.frontmatter["superseded_by_context_id"] == first_new.note_id
    assert first_new.status == "current"
    assert first_new.frontmatter["supersedes_context_id"] == first_old.note_id
    assert "original body must remain durable" in first_old.body
    assert "replacement body must remain durable" in first_new.body
    assert first_old.frontmatter["version"] == 2
    assert first_new.frontmatter["version"] == 2
    assert second_old.frontmatter["version"] == first_old.frontmatter["version"]
    assert second_new.frontmatter["version"] == first_new.frontmatter["version"]


def test_explicit_supersede_rejects_conflicting_existing_relation(
    tmp_path: Path,
) -> None:
    """An explicit second replacement must not alter the completed relation."""

    async def scenario() -> tuple[str, ObsidianNote, ObsidianNote]:
        database, session, service = await _service(tmp_path)
        try:
            for note_id, title in (
                ("ctx_conflict_old", "Conflict Old"),
                ("ctx_conflict_first", "Conflict First"),
                ("ctx_conflict_second", "Conflict Second"),
            ):
                await service.save_note(
                    _context_save(note_id, title, f"# {title}\n\ndurable body", {})
                )
            await service.supersede_context(
                "ctx_conflict_old",
                "ctx_conflict_first",
            )
            error = ""
            try:
                await service.supersede_context(
                    "ctx_conflict_old",
                    "ctx_conflict_second",
                )
            except ObsidianValidationError as exc:
                error = str(exc)
            return (
                error,
                await service.read_note("ctx_conflict_old"),
                await service.read_note("ctx_conflict_second"),
            )
        finally:
            await session.close()
            await database.shutdown()

    error, old, rejected_replacement = anyio.run(scenario)

    assert "INVALID_SUPERSEDE" in error
    assert old.frontmatter["superseded_by_context_id"] == "ctx_conflict_first"
    assert rejected_replacement.frontmatter.get("supersedes_context_id") is None
    assert rejected_replacement.status == "current"


def test_context_kind_and_aware_timestamps_survive_save_reindex_read(
    tmp_path: Path,
) -> None:
    """Canonical kind and aware timestamps must survive the full round trip."""
    created_at = datetime(2026, 7, 20, 1, 2, 3, tzinfo=UTC)
    updated_at = datetime(2026, 7, 21, 4, 5, 6, tzinfo=UTC)

    async def scenario() -> tuple[ContextRecord, list[str]]:
        database, session, service = await _service(tmp_path)
        try:
            saved = await service.save_note(
                _context_save(
                    "ctx_handoff_roundtrip",
                    "Handoff Roundtrip",
                    "# Handoff\n\nrestore exact canonical metadata",
                    {
                        "context_kind": "HANDOFF",
                        "created_at": created_at.isoformat(),
                        "updated_at": updated_at.isoformat(),
                    },
                )
            )
            rebuilt = await service.reindex()
            reread = await service.read_note(saved.note_id)
            return context_record_from_obsidian_note(reread), rebuilt.errors
        finally:
            await session.close()
            await database.shutdown()

    record, errors = anyio.run(scenario)

    assert errors == ()
    assert record.kind is ContextKind.HANDOFF
    assert record.created_at == created_at
    assert record.updated_at == updated_at
    assert record.created_at.utcoffset() is not None
    assert record.updated_at.utcoffset() is not None


def test_new_context_save_rejects_missing_explicit_scope(tmp_path: Path) -> None:
    """New canonical Context writes must not infer a missing scope."""

    async def scenario() -> tuple[str, bool]:
        database, session, service = await _service(tmp_path)
        expected_path = (
            tmp_path
            / "vault"
            / "Alexandria"
            / "Contexts"
            / "Projects"
            / "Missing Scope.md"
        )
        try:
            error = ""
            try:
                await service.save_note(
                    ObsidianSaveNote(
                        title="Missing Scope",
                        body="# Missing Scope\n\ninvalid inferred identity",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        note_id="ctx_missing_explicit_scope",
                        status="current",
                        project="project-a",
                    )
                )
            except ObsidianValidationError as exc:
                error = str(exc)
            return error, expected_path.exists()
        finally:
            await session.close()
            await database.shutdown()

    error, canonical_file_exists = anyio.run(scenario)

    assert "INVALID_SCOPE" in error
    assert canonical_file_exists is False


def test_repository_nested_transaction_recovers_after_sqlalchemy_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """One SQLAlchemy write error must not poison the next note upsert."""

    async def scenario() -> tuple[str, str]:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        repository = SqlAlchemyObsidianIndexRepository(session=session)
        root = tmp_path / "vault" / "Alexandria" / "Contexts" / "Projects"
        failed_path = root / "A Failed.md"
        valid_path = root / "B Valid.md"
        _write_context(failed_path, "ctx_sqlalchemy_failed", "A Failed")
        _write_context(valid_path, "ctx_sqlalchemy_valid", "B Valid")
        failed_payload = note_index_from_path(
            failed_path,
            "Alexandria/Contexts/Projects/A Failed.md",
            alexandria_root="Alexandria",
        )
        valid_payload = note_index_from_path(
            valid_path,
            "Alexandria/Contexts/Projects/B Valid.md",
            alexandria_root="Alexandria",
        )
        assert failed_payload is not None
        assert valid_payload is not None
        original_upsert = repository._upsert_note

        async def fail_one(payload: ObsidianNoteIndex) -> ObsidianNote:
            if payload.note_id == failed_payload.note_id:
                raise SQLAlchemyError("synthetic nested transaction failure")
            return await original_upsert(payload)

        monkeypatch.setattr(repository, "_upsert_note", fail_one)
        try:
            error = ""
            try:
                await repository.upsert_note(failed_payload)
            except ObsidianIndexWriteError as exc:
                error = str(exc)
            indexed = await repository.upsert_note(valid_payload)
            return error, indexed.note_id
        finally:
            await session.close()
            await database.shutdown()

    error, indexed_note_id = anyio.run(scenario)

    assert "failed to index Obsidian note" in error
    assert indexed_note_id == "ctx_sqlalchemy_valid"
