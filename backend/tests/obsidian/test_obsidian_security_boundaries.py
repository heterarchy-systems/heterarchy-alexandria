"""Security regression tests for canonical Obsidian Context boundaries."""

from __future__ import annotations

import os

from pathlib import Path

import anyio
from app.obsidian.application.notes.frontmatter.obsidian_frontmatter_redaction import (
    frontmatter_contains_secret_field,
    redacted_frontmatter,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianSearchQuery,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexErrorCode,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.infrastructure.database import Database
from sqlalchemy.ext.asyncio import AsyncSession


async def _service(tmp_path: Path) -> tuple[Database, AsyncSession, ObsidianService]:
    database = Database(
        database_url=os.environ["DATABASE_URL"],
        create_schema=True,
    )
    await database.initialize()
    session = database.session()
    service = ObsidianService(
        repository=SqlAlchemyObsidianIndexRepository(session=session),
        vault_path=str(tmp_path / "vault"),
        alexandria_root="Alexandria",
    )
    return database, session, service


def _raw_context(note_id: str, extra_frontmatter: str, body: str) -> str:
    return (
        "---\n"
        f"id: {note_id}\n"
        "alexandria_type: context\n"
        "title: Security Boundary\n"
        "scope: GLOBAL\n"
        "status: current\n"
        f"{extra_frontmatter}"
        "---\n\n"
        f"# Security Boundary\n\n{body}\n"
    )


def test_false_secret_recording_audit_marker_is_not_treated_as_a_credential() -> None:
    """An exact false audit marker should remain while true/secret fields stay blocked."""
    safe_markdown = _raw_context(
        "ctx_safe_audit",
        "secret_values_recorded: false\n",
        "safe",
    )
    unsafe_markdown = _raw_context(
        "ctx_unsafe_audit",
        "secret_values_recorded: true\n",
        "unsafe",
    )

    redacted, warnings = redacted_frontmatter(
        {
            "secret_values_recorded": False,
            "token": "credential-like-value",
        }
    )

    assert frontmatter_contains_secret_field(safe_markdown) is False
    assert frontmatter_contains_secret_field(unsafe_markdown) is True
    assert redacted == {"secret_values_recorded": False}
    assert warnings == ["potential secret-like frontmatter field was redacted"]


def test_reindex_rejects_symlinked_markdown_without_reading_external_content(
    tmp_path: Path,
) -> None:
    """Vault scans must not index Markdown reached through a symlink."""

    async def scenario() -> tuple[list[ObsidianIndexErrorCode], list[str]]:
        database, session, service = await _service(tmp_path)
        external = tmp_path / "outside.md"
        external.write_text(
            _raw_context("ctx_external", "", "external-secret-marker"),
            encoding="utf-8",
        )
        managed = tmp_path / "vault" / "Alexandria" / "Contexts"
        managed.mkdir(parents=True)
        (managed / "Outside.md").symlink_to(external)
        try:
            rebuilt = await service.reindex()
            hits = await service.search(
                ObsidianSearchQuery(query="external-secret-marker", limit=5),
                refresh=False,
            )
            return [detail.error_code for detail in rebuilt.error_details], [
                hit.note.note_id for hit in hits
            ]
        finally:
            await session.close()
            await database.shutdown()

    error_codes, note_ids = anyio.run(scenario)

    assert error_codes == [ObsidianIndexErrorCode.PATH_SECURITY_VIOLATION]
    assert note_ids == []


def test_unique_atomic_note_write_ignores_preplaced_predictable_temp_symlink(
    tmp_path: Path,
) -> None:
    """Save and archive must not follow an attacker-controlled .md.tmp path."""

    async def scenario() -> tuple[str, str]:
        database, session, service = await _service(tmp_path)
        directory = tmp_path / "vault" / "Alexandria" / "Contexts" / "Projects"
        directory.mkdir(parents=True)
        sentinel = tmp_path / "outside-sentinel.txt"
        sentinel.write_text("unchanged", encoding="utf-8")
        predictable_temp = directory / "Safe.md.tmp"
        predictable_temp.symlink_to(sentinel)
        try:
            saved = await service.save_note(
                ObsidianSaveNote(
                    note_id="ctx_atomic_safe",
                    title="Atomic Safe",
                    body="# Atomic Safe\n\nDurable content",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    relative_path="Alexandria/Contexts/Projects/Safe.md",
                    project="project-a",
                    status="current",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            await service.archive_context(saved.note_id)
            return sentinel.read_text(encoding="utf-8"), predictable_temp.read_text(
                encoding="utf-8"
            )
        finally:
            await session.close()
            await database.shutdown()

    sentinel_text, symlink_target_text = anyio.run(scenario)

    assert sentinel_text == "unchanged"
    assert symlink_target_text == "unchanged"


def test_secret_named_frontmatter_is_removed_on_save_and_quarantined_on_reindex(
    tmp_path: Path,
) -> None:
    """Secret-like keys must never reach canonical Markdown or the search index."""

    async def scenario() -> tuple[str, list[ObsidianIndexErrorCode], list[str], str]:
        database, session, service = await _service(tmp_path)
        try:
            saved = await service.save_note(
                ObsidianSaveNote(
                    note_id="ctx_redacted_secret",
                    title="Redacted Secret",
                    body="# Redacted Secret\n\nSafe body",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    relative_path="Alexandria/Contexts/Redacted.md",
                    status="current",
                    frontmatter={"scope": "GLOBAL", "password": "hunter2"},
                )
            )
            saved_text = (tmp_path / "vault" / saved.relative_path).read_text(
                encoding="utf-8"
            )
            raw_path = tmp_path / "vault" / "Alexandria" / "Contexts" / "Raw.md"
            raw_path.write_text(
                _raw_context("ctx_raw_secret", "token: abc123456789\n", "safe"),
                encoding="utf-8",
            )
            rebuilt = await service.reindex()
            hits = await service.search(
                ObsidianSearchQuery(query="abc123456789", limit=5),
                refresh=False,
            )
            status = await service.status()
            messages = " ".join(error.error_message for error in status.index_errors)
            return (
                saved_text,
                [detail.error_code for detail in rebuilt.error_details],
                [hit.note.note_id for hit in hits],
                messages,
            )
        finally:
            await session.close()
            await database.shutdown()

    saved_text, error_codes, note_ids, messages = anyio.run(scenario)

    assert "password" not in saved_text
    assert "hunter2" not in saved_text
    assert ObsidianIndexErrorCode.FRONTMATTER_SECRET_DETECTED in error_codes
    assert note_ids == []
    assert "abc123456789" not in messages


def test_duplicate_lifecycle_key_and_raw_invalid_enum_are_safely_quarantined(
    tmp_path: Path,
) -> None:
    """Ambiguous lifecycle and malicious enum input must not leak or index."""

    async def scenario() -> tuple[list[ObsidianIndexErrorCode], str]:
        database, session, service = await _service(tmp_path)
        directory = tmp_path / "vault" / "Alexandria" / "Contexts"
        directory.mkdir(parents=True)
        (directory / "Duplicate.md").write_text(
            _raw_context("ctx_duplicate_status", "status: active\n", "safe"),
            encoding="utf-8",
        )
        raw_secret = "token-should-not-be-reflected"
        (directory / "Invalid Type.md").write_text(
            "---\n"
            "id: ctx_invalid_type\n"
            f"alexandria_type: {raw_secret}\n"
            "---\n\n# Invalid\n",
            encoding="utf-8",
        )
        try:
            rebuilt = await service.reindex()
            status = await service.status()
            serialized_messages = " ".join(
                error.error_message for error in status.index_errors
            )
            return [detail.error_code for detail in rebuilt.error_details], (
                serialized_messages
            )
        finally:
            await session.close()
            await database.shutdown()

    error_codes, messages = anyio.run(scenario)

    assert error_codes.count(ObsidianIndexErrorCode.FRONTMATTER_PARSE_ERROR) == 2
    assert "token-should-not-be-reflected" not in messages
