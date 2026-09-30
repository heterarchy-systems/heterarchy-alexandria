"""Byte-preserving frontmatter repair and raw repair safety tests."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianValidationError,
    ObsidianWriteConflictError,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models

_UNICODE_BODY = "# 유니콘 바디\n\n보존되어야 하는 본문 — em-dash — and emoji 🛡️\n"


async def _services(tmp_path: Path) -> tuple[Database, AsyncSession, ObsidianService]:
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    session = database.session()
    repository = SqlAlchemyObsidianIndexRepository(session=session)
    obsidian = ObsidianService(
        repository=repository,
        vault_path=str(tmp_path / "vault"),
        alexandria_root="Alexandria",
    )
    return database, session, obsidian


async def _seed_note(
    obsidian: ObsidianService,
    tmp_path: Path,
    *,
    text: str,
) -> str:
    """Write one raw managed note directly and return its vault path."""
    path = tmp_path / "vault" / "Alexandria" / "Stale.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return "Alexandria/Stale.md"


def test_bounded_revalidation_repairs_managed_hash_without_rewriting_body(
    tmp_path: Path,
) -> None:
    """Known hash integrity damage is repaired locally behind the preview's exact CAS."""

    async def scenario():
        database, session, obsidian = await _services(tmp_path)
        body = "\r\n# Keep these bytes\r\n가나다 🛡️\r\n\r\n"
        source = (
            "---\nid: ctx_recovery\nalexandria_type: context\ntitle: Recovery\nproject: Project\nscope: PROJECT\nstatus: active\ncontent_hash: wrong\nversion: 7\n---\n"
            + body
        )
        path = await _seed_note(obsidian, tmp_path, text=source)
        try:
            raw = await obsidian.read_note_raw(path=path)
            assert raw.content_hash is not None
            with pytest.raises(ObsidianWriteConflictError):
                await obsidian.revalidate_note_index(
                    path=path, expected_source_hash="0" * 64
                )
            note = await obsidian.revalidate_note_index(
                path=path, expected_source_hash=raw.content_hash
            )
            assert note.index_status.value == "indexed"
            assert (tmp_path / "vault" / path).read_bytes().endswith(body.encode())
            assert note.frontmatter["version"] == 7
            new_raw = await obsidian.read_note_raw(path=path)
            assert new_raw.parse_status == "OK"
            again = await obsidian.revalidate_note_index(
                path=path, expected_source_hash=new_raw.content_hash
            )
            assert again.content_hash == note.content_hash
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


@pytest.mark.parametrize(
    "body", [_UNICODE_BODY, "\r\n" + _UNICODE_BODY.replace("\n", "\r\n") + "\r\n\r\n"]
)
def test_frontmatter_repair_preserves_unicode_body_bytes(
    tmp_path: Path, body: str
) -> None:
    """Stale frontmatter with a valid body repairs without touching body bytes."""

    async def scenario() -> tuple[object, ...]:
        database, session, obsidian = await _services(tmp_path)
        try:
            original = (
                "---\nid: ctx_stale\nalexandria_type: context\n"
                "title: Stale\nproject: Project\nstatus: active\n"
                f"version: 3\ncontent_hash: {'a' * 64}\n---\n{body}"
            )
            vault_path = await _seed_note(obsidian, tmp_path, text=original)
            raw = await obsidian.read_note_raw(path=vault_path)
            assert raw.byte_exact is True
            assert raw.content_hash is not None
            replacement = {
                "id": "ctx_stale",
                "alexandria_type": "context",
                "title": "Stale",
                "project": "Project",
                "status": "active",
                "version": 4,
                "content_hash": "b" * 64,
            }
            with pytest.raises(ObsidianValidationError, match="SERVER_OWNED"):
                await obsidian.repair_note_frontmatter(
                    path=vault_path,
                    expected_content_hash=raw.content_hash,
                    replacement_frontmatter=replacement,
                )
            assert (
                tmp_path / "vault" / "Alexandria" / "Stale.md"
            ).read_bytes() == original.encode("utf-8")
            del replacement["version"]
            del replacement["content_hash"]
            result = await obsidian.repair_note_frontmatter(
                path=vault_path,
                expected_content_hash=raw.content_hash,
                replacement_frontmatter=replacement,
            )
            assert result.body_byte_exact_preserved is True
            assert result.body_hash_before == result.body_hash_after
            assert result.content_hash_before == raw.content_hash
            assert result.content_hash_after != result.content_hash_before
            assert result.removed_server_owned_fields == ("content_hash", "version")
            assert result.parse_status == "OK"
            reread = await obsidian.read_note_raw(path=vault_path)
            assert (
                (tmp_path / "vault" / "Alexandria" / "Stale.md")
                .read_bytes()
                .endswith(body.encode("utf-8"))
            )
            assert reread.parse_status == "OK"
            note = await obsidian.read_note_by_path(vault_path)
            assert note.frontmatter.get("status") == "active"
            assert isinstance(note.frontmatter.get("version"), int)
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_frontmatter_repair_rejects_stale_cas_and_placeholders(
    tmp_path: Path,
) -> None:
    """Stale CAS fails closed and placeholder payloads are refused."""

    async def scenario() -> None:
        database, session, obsidian = await _services(tmp_path)
        try:
            original = (
                "---\nid: ctx_stale\nalexandria_type: context\ntitle: Stale\n"
                f"---\n{_UNICODE_BODY}"
            )
            vault_path = await _seed_note(obsidian, tmp_path, text=original)
            raw = await obsidian.read_note_raw(path=vault_path)
            assert raw.content_hash is not None
            with pytest.raises(ObsidianWriteConflictError) as conflict:
                await obsidian.repair_note_frontmatter(
                    path=vault_path,
                    expected_content_hash="0" * 64,
                    replacement_frontmatter={"id": "ctx_stale"},
                )
            assert conflict.value.current_content_hash == raw.content_hash
            with pytest.raises(ObsidianValidationError, match="PLACEHOLDER"):
                await obsidian.repair_note_frontmatter(
                    path=vault_path,
                    expected_content_hash=raw.content_hash,
                    replacement_frontmatter={
                        "id": "ctx_stale",
                        "source_url": "https://example.com/<REDACTED_LONG_VALUE>",
                    },
                )
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_repair_note_raw_rejects_placeholder_and_masked_payloads(
    tmp_path: Path,
) -> None:
    """Raw repair never persists masked or placeholder content."""

    async def scenario() -> None:
        database, session, obsidian = await _services(tmp_path)
        try:
            original = (
                "---\nid: ctx_stale\nalexandria_type: context\ntitle: Stale\n"
                "---\nbody\n"
            )
            vault_path = await _seed_note(obsidian, tmp_path, text=original)
            raw = await obsidian.read_note_raw(path=vault_path)
            assert raw.content_hash is not None
            with pytest.raises(ObsidianValidationError, match="PLACEHOLDER"):
                await obsidian.repair_note_raw(
                    path=vault_path,
                    expected_content_hash=raw.content_hash,
                    raw_content=(
                        "---\nid: ctx_stale\nurl: https://x/<REDACTED_LONG_VALUE>\n"
                        "---\nbody\n"
                    ),
                )
            with pytest.raises(ObsidianValidationError, match="REDACTED"):
                await obsidian.repair_note_raw(
                    path=vault_path,
                    expected_content_hash=raw.content_hash,
                    raw_content=(
                        "---\nid: ctx_stale\napi_key: Abcdef123456\n---\nbody\n"
                    ),
                )
            untouched = await obsidian.read_note_raw(path=vault_path)
            assert untouched.content_hash == raw.content_hash
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_read_note_raw_reports_suppressed_view_as_not_byte_exact(
    tmp_path: Path,
) -> None:
    """Secret-suppressed raw reads explicitly declare they are not byte-exact."""

    async def scenario() -> tuple[bool, str, str]:
        database, session, obsidian = await _services(tmp_path)
        try:
            secret_note = tmp_path / "vault" / "Alexandria" / "Secret.md"
            secret_note.parent.mkdir(parents=True, exist_ok=True)
            secret_note.write_text(
                "---\nid: ctx_secret\napi_key: supersecretvalue123\n---\nbody\n",
                encoding="utf-8",
            )
            read = await obsidian.read_note_raw(path="Alexandria/Secret.md")
            return read.byte_exact, read.raw_text or "", read.parse_status
        finally:
            await session.close()
            await database.shutdown()

    byte_exact, raw_text, parse_status = anyio.run(scenario)

    assert byte_exact is False
    assert raw_text == ""
    assert parse_status == "FRONTMATTER_SECRET_DETECTED"
