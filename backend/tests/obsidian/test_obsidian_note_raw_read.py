"""Raw malformed-note read behavior tests for the Obsidian note service."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


async def _services(
    tmp_path: Path,
) -> tuple[Database, AsyncSession, ObsidianService]:
    database = Database(database_url=_database_url(), create_schema=True)
    await database.initialize()
    session = database.session()
    repository = SqlAlchemyObsidianIndexRepository(session=session)
    obsidian = ObsidianService(
        repository=repository,
        vault_path=str(tmp_path / "vault"),
        alexandria_root="Alexandria",
    )
    return database, session, obsidian


def test_read_note_raw_returns_parse_error_for_malformed_frontmatter(
    tmp_path: Path,
) -> None:
    """A note with an unterminated frontmatter block stays raw-readable."""

    async def scenario() -> tuple[str, str, str | None]:
        database, session, obsidian = await _services(tmp_path)
        try:
            broken = tmp_path / "vault" / "Alexandria" / "Broken.md"
            broken.parent.mkdir(parents=True, exist_ok=True)
            text = "---\nid: ctx_broken\n"
            broken.write_text(text, encoding="utf-8")
            read = await obsidian.read_note_raw(path="Alexandria/Broken.md")
        finally:
            await session.close()
            await database.shutdown()
        return read.parse_status, read.raw_text or "", read.content_hash

    parse_status, raw_text, content_hash = anyio.run(scenario)

    assert parse_status == "FRONTMATTER_PARSE_ERROR"
    assert raw_text == "---\nid: ctx_broken\n"
    assert content_hash is not None


def test_read_note_raw_reads_valid_context_note(tmp_path: Path) -> None:
    """A saved CONTEXT note reads back as OK with frontmatter and body."""

    async def scenario() -> tuple[str, str, str | None]:
        database, session, obsidian = await _services(tmp_path)
        try:
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Raw Read OK",
                    body="# Raw Read OK\n\nPlain body.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_raw_read_ok",
                    relative_path="Alexandria/Raw Read OK.md",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            read = await obsidian.read_note_raw(path="Alexandria/Raw Read OK.md")
        finally:
            await session.close()
            await database.shutdown()
        return read.parse_status, read.body or "", (read.frontmatter or {}).get("id")

    parse_status, body, frontmatter_id = anyio.run(scenario)

    assert parse_status == "OK"
    assert "# Raw Read OK" in body
    assert frontmatter_id == "ctx_raw_read_ok"


def test_read_note_raw_raises_not_found_for_missing_file(tmp_path: Path) -> None:
    """A missing source file raises ObsidianNotFoundError."""

    async def scenario() -> None:
        database, session, obsidian = await _services(tmp_path)
        try:
            await obsidian.read_note_raw(path="Alexandria/Missing.md")
        finally:
            await session.close()
            await database.shutdown()

    with pytest.raises(ObsidianNotFoundError):
        anyio.run(scenario)


_REPAIRED_SOURCE = (
    "---\nid: ctx_broken\ntitle: Broken\n"
    "alexandria_type: context\nscope: GLOBAL\n---\n"
    "# Broken\n\nrepaired body\n"
)


def test_repair_note_raw_recovers_malformed_note_in_place(tmp_path: Path) -> None:
    """Read raw → fix → CAS replace recovers a malformed note without a rewrite."""

    async def scenario() -> tuple[str, str, str | None]:
        database, session, obsidian = await _services(tmp_path)
        try:
            broken = tmp_path / "vault" / "Alexandria" / "Broken.md"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text("---\nid: ctx_broken\n", encoding="utf-8")
            raw = await obsidian.read_note_raw(path="Alexandria/Broken.md")
            assert raw.content_hash is not None
            repaired = await obsidian.repair_note_raw(
                path="Alexandria/Broken.md",
                expected_content_hash=raw.content_hash,
                raw_content=_REPAIRED_SOURCE,
            )
            reread = await obsidian.read_note_raw(path="Alexandria/Broken.md")
        finally:
            await session.close()
            await database.shutdown()
        return repaired.note_id, reread.parse_status, reread.content_hash

    note_id, parse_status, repaired_hash = anyio.run(scenario)

    assert note_id == "ctx_broken"
    assert parse_status == "OK"
    assert repaired_hash is not None


def test_repair_note_raw_conflict_carries_current_hash(tmp_path: Path) -> None:
    """A stale expected hash is rejected with the current hash attached."""

    async def scenario() -> str | None:
        database, session, obsidian = await _services(tmp_path)
        try:
            broken = tmp_path / "vault" / "Alexandria" / "Broken.md"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text("---\nid: ctx_broken\n", encoding="utf-8")
            try:
                await obsidian.repair_note_raw(
                    path="Alexandria/Broken.md",
                    expected_content_hash="stale-hash",
                    raw_content=_REPAIRED_SOURCE,
                )
            except ObsidianWriteConflictError as exc:
                return exc.current_content_hash
            raise AssertionError("repair should have conflicted")
        finally:
            await session.close()
            await database.shutdown()

    current_hash = anyio.run(scenario)

    assert current_hash is not None


def test_repair_note_raw_rejects_unparseable_replacement(tmp_path: Path) -> None:
    """A replacement that still fails to parse is rejected before writing."""

    async def scenario() -> str:
        database, session, obsidian = await _services(tmp_path)
        try:
            broken = tmp_path / "vault" / "Alexandria" / "Broken.md"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text("---\nid: ctx_broken\n", encoding="utf-8")
            raw = await obsidian.read_note_raw(path="Alexandria/Broken.md")
            try:
                await obsidian.repair_note_raw(
                    path="Alexandria/Broken.md",
                    expected_content_hash=raw.content_hash or "",
                    raw_content="still broken",
                )
            except ObsidianValidationError as exc:
                message = str(exc)
            on_disk = broken.read_text(encoding="utf-8")
        finally:
            await session.close()
            await database.shutdown()
        assert on_disk == "---\nid: ctx_broken\n"
        return message

    message = anyio.run(scenario)

    assert "missing Alexandria frontmatter" in message
