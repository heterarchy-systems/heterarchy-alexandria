"""Bounded server-side body patch tests."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
)
from app.obsidian.application.notes.writing import (
    obsidian_note_persistence as note_persistence_module,
)
from app.obsidian.application.notes.writing.obsidian_note_body_patch import (
    ObsidianNoteBodyPatchResult,
)
from app.obsidian.application.service.notes.obsidian_body_patch import (
    validate_body_patch_replacements,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexStatus
from app.obsidian.infrastructure.markdown import atomic_markdown_write
from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_json,
    parse_markdown_document,
)
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.obsidian.interface.schemas.obsidian.notes.obsidian_source_schema import (
    ObsidianBodyPatchRequest,
    ObsidianBodyPatchResponse,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIndexWriteError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


async def _services(tmp_path: Path) -> tuple[Database, AsyncSession, ObsidianService]:
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    session = database.session()
    repository = SqlAlchemyObsidianIndexRepository(session=session)
    service = ObsidianService(
        repository=repository,
        vault_path=str(tmp_path / "vault"),
        alexandria_root="Alexandria",
    )
    return database, session, service


def test_body_patch_directory_fsync_failure_keeps_commit_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Visible replacement bytes do not prove a failed directory fsync committed."""

    async def scenario() -> None:
        database, session, service = await _services(tmp_path)
        source_path = tmp_path / "vault" / "Alexandria" / "Durability.md"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        original_body = "before durability patch\n"
        body_hash = context_content_hash(
            parse_markdown_document("---\n---\n" + original_body).body
        )
        source_path.write_text(
            "---\nid: ctx_patch_durability\nalexandria_type: context\n"
            "title: Durability\nproject: Project\nscope: PROJECT\nstatus: active\n"
            f"content_hash: {body_hash}\n---\n{original_body}",
            encoding="utf-8",
        )
        original_bytes = source_path.read_bytes()
        original_sync = atomic_markdown_write._sync_directory

        def fail_after_replace(path: Path) -> None:
            if path == source_path.parent:
                assert b"after durability patch" in source_path.read_bytes()
                raise OSError("synthetic directory fsync failure")
            original_sync(path)

        try:
            raw = await service.read_note_raw(path="Alexandria/Durability.md")
            assert raw.content_hash is not None
            with monkeypatch.context() as patcher:
                patcher.setattr(
                    atomic_markdown_write, "_sync_directory", fail_after_replace
                )
                with pytest.raises(
                    ObsidianValidationError, match="BODY_PATCH_COMMIT_UNVERIFIED"
                ):
                    await service.patch_note_body(
                        path="Alexandria/Durability.md",
                        expected_content_hash=raw.content_hash,
                        replacements=(
                            ("before durability patch", "after durability patch"),
                        ),
                    )
            assert source_path.read_bytes() != original_bytes
            assert b"after durability patch" in source_path.read_bytes()
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_body_patch_preserves_unsubmitted_source_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply exact body spans without sending the existing document to callers."""

    async def scenario() -> None:
        database, session, service = await _services(tmp_path)
        try:
            source_path = tmp_path / "vault" / "Alexandria" / "Synthetic.md"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            body_bytes = (
                b"covered-through21 is historical.\r\n"
                b"<REDACTED_LONG_VALUE> <REDACTED_LONG_VALUE> "
                b"<REDACTED_LONG_VALUE> <REDACTED_LONG_VALUE> "
                b"<REDACTED_LONG_VALUE>\r\n"
                b"opaque_history_value_0123456789abcdefghijklmnopqrstuvwxyzABCDEF\r\n"
                b"overlap-marker\r\n"
                b"patch-one patch-two patch-three patch-four "
                b"patch-five patch-six patch-seven patch-eight\r\n"
                b"duplicate-target duplicate-target\r\n"
                b"bearer X\r\n"
            )
            normalized_initial_body = parse_markdown_document(
                "---\n---\n" + body_bytes.decode("utf-8")
            ).body
            original_context_hash = context_content_hash(normalized_initial_body)
            original_bytes = (
                b"---\r\n"
                b"id: ctx_synthetic_patch\r\n"
                b"alexandria_type: context\r\n"
                b"title: Synthetic # preserve this comment\r\n"
                b"project: Project\r\n"
                b"scope: PROJECT\r\n"
                b"status: active\r\n"
                b"content_hash: " + original_context_hash.encode("ascii") + b"\r\n"
                b"version: 7\r\n"
                b"---\r\n" + body_bytes
            )
            source_path.write_bytes(original_bytes)
            raw = await service.read_note_raw(path="Alexandria/Synthetic.md")
            assert raw.content_hash is not None

            with pytest.raises(ObsidianWriteConflictError):
                await service.patch_note_body(
                    path="Alexandria/Synthetic.md",
                    expected_content_hash="0" * 64,
                    replacements=(("covered-through21", "stale attempt"),),
                )
            assert source_path.read_bytes() == original_bytes

            original_persist_and_index = note_persistence_module.persist_and_index
            drift_bytes = original_bytes.replace(
                b"covered-through21 is historical.",
                b"external synthetic change remains durable.",
                1,
            )

            def drift_before_persist(*args, **kwargs):
                source_path.write_bytes(drift_bytes)
                return original_persist_and_index(*args, **kwargs)

            with monkeypatch.context() as patcher:
                patcher.setattr(
                    note_persistence_module,
                    "persist_and_index",
                    drift_before_persist,
                )
                with pytest.raises(ObsidianWriteConflictError):
                    await service.patch_note_body(
                        path="Alexandria/Synthetic.md",
                        expected_content_hash=raw.content_hash,
                        replacements=(("covered-through21", "stale attempt"),),
                    )
            assert source_path.read_bytes() == drift_bytes
            source_path.write_bytes(original_bytes)

            readback_drift_bytes = original_bytes.replace(
                b"covered-through21 is historical.",
                b"third-party readback drift remains durable.",
                1,
            )
            original_upsert = service._repository.upsert_note
            upsert_called = False

            async def capture_unexpected_upsert(payload):
                nonlocal upsert_called
                upsert_called = True
                return await original_upsert(payload)

            def drift_after_index(*args, **kwargs):
                payload = original_persist_and_index(*args, **kwargs)
                source_path.write_bytes(readback_drift_bytes)
                return payload

            with monkeypatch.context() as patcher:
                patcher.setattr(
                    note_persistence_module,
                    "persist_and_index",
                    drift_after_index,
                )
                patcher.setattr(
                    service._repository,
                    "upsert_note",
                    capture_unexpected_upsert,
                )
                with pytest.raises(ObsidianWriteConflictError):
                    await service.patch_note_body(
                        path="Alexandria/Synthetic.md",
                        expected_content_hash=raw.content_hash,
                        replacements=(("covered-through21", "readback drift attempt"),),
                    )
            assert source_path.read_bytes() == readback_drift_bytes
            assert upsert_called is False
            source_path.write_bytes(original_bytes)

            async def assert_rejected(
                replacements: tuple[tuple[str, str], ...],
            ) -> None:
                with pytest.raises(ObsidianValidationError):
                    await service.patch_note_body(
                        path="Alexandria/Synthetic.md",
                        expected_content_hash=raw.content_hash,
                        replacements=replacements,
                    )
                assert source_path.read_bytes() == original_bytes

            await assert_rejected((("not-present", "replacement"),))
            await assert_rejected((("duplicate-target", "replacement"),))
            await assert_rejected((("overlap", "replacement"), ("lap-marker", "other")))
            await assert_rejected(
                (("covered-through21", "one"), ("covered-through21", "two"))
            )
            await assert_rejected((("title: Synthetic", "caller-frontmatter"),))
            await assert_rejected((("<REDACTED_LONG_VALUE>", "replacement"),))
            await assert_rejected((("covered-through21", "<REDACTED>"),))
            await assert_rejected(
                (("api_key=abcdefghijklmnopqrstuvwxyz0123456789", "safe"),)
            )
            await assert_rejected((("LONG_VALUE", "changed"),))
            await assert_rejected((("history_value_0123456789", "changed"),))
            await assert_rejected((("X", "abcd1234"),))
            await assert_rejected(
                tuple((f"old-{index}", f"new-{index}") for index in range(9))
            )
            assert (
                len(
                    validate_body_patch_replacements(
                        tuple((f"old-{index}", f"new-{index}") for index in range(8))
                    )
                )
                == 8
            )

            replacements = (
                ("covered-through21", "covered-through21; bounded patch"),
                ("patch-one", "patched-one"),
                ("patch-two", "patched-two"),
                ("patch-three", "patched-three"),
                ("patch-four", "patched-four"),
                ("patch-five", "patched-five"),
                ("patch-six", "patched-six"),
                ("patch-seven", "patched-seven"),
            )

            result = await service.patch_note_body(
                path="Alexandria/Synthetic.md",
                expected_content_hash=raw.content_hash,
                replacements=replacements,
            )
            expected_body = (
                original_bytes.split(b"---\r\n", maxsplit=1)[1]
                .split(b"\r\n---\r\n", maxsplit=1)[1]
                .decode("utf-8")
            )
            for old_text, new_text in replacements:
                expected_body = expected_body.replace(old_text, new_text, 1)
            normalized_expected_body = parse_markdown_document(
                "---\n---\n" + expected_body
            ).body
            updated_context_hash = context_content_hash(normalized_expected_body)
            expected_bytes = original_bytes.replace(
                f"content_hash: {original_context_hash}".encode("ascii"),
                f"content_hash: {updated_context_hash}".encode(),
                1,
            )
            for old_text, new_text in replacements:
                expected_bytes = expected_bytes.replace(
                    old_text.encode("utf-8"),
                    new_text.encode("utf-8"),
                    1,
                )
            durable_bytes = source_path.read_bytes()
            parsed = parse_markdown_document(durable_bytes.decode("utf-8"))
            parsed_frontmatter = frontmatter_json(parsed.frontmatter)
            indexed = await service.read_note_by_path("Alexandria/Synthetic.md")

            assert result.note_id == "ctx_synthetic_patch"
            assert result.relative_path == "Alexandria/Synthetic.md"
            assert result.content_hash_before == raw.content_hash
            assert result.content_hash_after != result.content_hash_before
            assert result.index_status is ObsidianIndexStatus.INDEXED
            assert result.body_replacement_count == 8
            assert result.changed_span_count == 9
            assert result.managed_content_hash_updated is True
            assert result.source_persisted is True
            assert result.untouched_source_bytes_preserved is True
            assert durable_bytes == expected_bytes
            assert parsed_frontmatter["content_hash"] == updated_context_hash
            assert parsed.body == normalized_expected_body
            assert indexed.note_id == "ctx_synthetic_patch"
            assert indexed.index_status is ObsidianIndexStatus.INDEXED
            assert durable_bytes.count(b"<REDACTED_LONG_VALUE>") == 5
            assert (
                b"opaque_history_value_0123456789abcdefghijklmnopqrstuvwxyzABCDEF"
                in durable_bytes
            )
            assert b"\r\n" in durable_bytes

            active_target = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Skills"
                / "Active"
                / "synthetic-active.md"
            )
            active_target.parent.mkdir(parents=True, exist_ok=True)
            active_target.write_bytes(original_bytes)
            alias_path = (
                tmp_path / "vault" / "Alexandria" / "Projects" / "Active Alias.md"
            )
            alias_path.parent.mkdir(parents=True, exist_ok=True)
            alias_path.symlink_to(active_target)
            with pytest.raises(
                ObsidianValidationError, match="PATH_SECURITY_VIOLATION"
            ):
                await service.patch_note_body(
                    path="Alexandria/Projects/Active Alias.md",
                    expected_content_hash=raw.content_hash,
                    replacements=(("covered-through21", "alias attempt"),),
                )
            with pytest.raises(
                ObsidianValidationError,
                match="BODY_PATCH_SKILL_PATH_UNSUPPORTED",
            ):
                await service.patch_note_body(
                    path="Alexandria/Skills/Active/synthetic-active.md",
                    expected_content_hash=raw.content_hash,
                    replacements=(("covered-through21", "skill attempt"),),
                )
            assert active_target.read_bytes() == original_bytes
            assert alias_path.is_symlink()

            current_raw = await service.read_note_raw(path="Alexandria/Synthetic.md")
            assert current_raw.content_hash is not None
            repository = service._repository

            async def fail_index(_payload) -> None:
                raise ObsidianIndexWriteError("synthetic index failure")

            monkeypatch.setattr(repository, "upsert_note", fail_index)
            failed_index_result = await service.patch_note_body(
                path="Alexandria/Synthetic.md",
                expected_content_hash=current_raw.content_hash,
                replacements=(("bounded patch", "persisted despite index error"),),
            )
            assert failed_index_result.source_persisted is True
            assert failed_index_result.index_status is ObsidianIndexStatus.ERROR
            assert b"persisted despite index error" in source_path.read_bytes()
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_body_patch_http_schema_never_exposes_source_body() -> None:
    """The HTTP contract accepts spans but its response contains no body field."""
    assert any(
        getattr(route, "path", None) == "/obsidian/notes/body-patch"
        and "PATCH" in getattr(route, "methods", set())
        for route in app.routes
    )
    with pytest.raises(ValueError):
        validate_body_patch_replacements((("ordinary text", "contains\x00nul"),))
    request = ObsidianBodyPatchRequest.model_validate(
        {
            "path": "Alexandria/Contexts/Synthetic.md",
            "expected_content_hash": "a" * 64,
            "replacements": [{"old_text": "old span", "new_text": "new span"}],
        }
    )
    assert request.replacements[0].old_text == "old span"
    assert set(ObsidianBodyPatchResponse.model_fields) == {
        "relative_path",
        "note_id",
        "content_hash_before",
        "content_hash_after",
        "index_status",
        "body_replacement_count",
        "changed_span_count",
        "managed_content_hash_updated",
        "source_persisted",
        "untouched_source_bytes_preserved",
    }

    response = ObsidianBodyPatchResponse.from_entity(
        ObsidianNoteBodyPatchResult(
            relative_path="Alexandria/Contexts/Synthetic.md",
            note_id="ctx_synthetic_patch",
            content_hash_before="a" * 64,
            content_hash_after="b" * 64,
            index_status=ObsidianIndexStatus.INDEXED,
            body_replacement_count=1,
            changed_span_count=2,
            managed_content_hash_updated=True,
            source_persisted=True,
            untouched_source_bytes_preserved=True,
        )
    )
    payload = response.model_dump_json()
    assert "old span" not in payload
    assert "new span" not in payload
    assert "body" not in ObsidianBodyPatchResponse.model_fields
