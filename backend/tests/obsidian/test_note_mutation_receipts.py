"""General note mutations reconcile response loss without duplicate source writes."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from tests.obsidian.test_obsidian_frontmatter_repair import _services

from app.obsidian.application.service.notes.obsidian_mutation_outcome_service import (
    ObsidianMutationOutcomeService,
)
from app.obsidian.application.service.notes.obsidian_note_mutation_receipts import (
    NoteMutationReceipts,
    note_mutation_id,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
    ObsidianIdempotencyConflictError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)
from app.shared.types.extra_types import JSONObject


def test_create_response_loss_replay_update_and_conflict_receipts(
    tmp_path: Path,
) -> None:
    """Ignored create response, exact CREATE replay and CAS update share durable identity."""

    async def scenario():
        database, session, service = await _services(tmp_path)
        outcomes = ObsidianMutationOutcomeService(
            service,
            ObsidianVaultConfigStore(
                default_vault_path=str(tmp_path / "vault"),
                default_alexandria_root="Alexandria",
                config_path=None,
            ),
        )
        command = ObsidianWriteNote(
            note=ObsidianSaveNote(
                title="Receipt",
                body="# Original",
                alexandria_type=AlexandriaNoteType.JOB_PLAN,
                relative_path="Alexandria/Job Plans/Receipt.md",
                idempotency_key="create-one",
            ),
            write_mode=ObsidianWriteMode.CREATE,
            match_by=ObsidianWriteMatchBy.PATH,
        )
        try:
            await service.write_note(command)  # caller lost the response
            await session.commit()
            outcome = await outcomes.note_write_outcome("create-one")
            assert outcome.status.value == "COMMITTED"
            assert (
                outcome.mutation_id
                and outcome.operation_identity
                and outcome.committed_at
            )
            direct = await outcomes.note_write_outcome(
                mutation_id=outcome.mutation_id,
            )
            assert direct.status.value == "COMMITTED"
            assert direct.idempotency_key == "create-one"
            assert direct.operation_identity == outcome.operation_identity
            assert direct.mutation_id == outcome.mutation_id
            missing_direct = await outcomes.note_write_outcome(
                mutation_id=note_mutation_id("never-admitted-direct"),
            )
            assert missing_direct.status.value == "NOT_COMMITTED"
            assert missing_direct.idempotency_key is None
            assert missing_direct.mutation_id == note_mutation_id(
                "never-admitted-direct"
            )
            assert command.note.relative_path is not None
            path = tmp_path / "vault" / command.note.relative_path
            original = path.read_bytes()
            replay = await service.write_note(command)
            assert replay.operation.value == "unchanged"
            assert replay.note.mutation_receipt is not None
            assert replay.note.mutation_receipt.replayed is True
            assert path.read_bytes() == original
            assert len(list((tmp_path / "vault" / "Alexandria").rglob("*.md"))) == 1
            with pytest.raises(ObsidianIdempotencyConflictError):
                await service.write_note(
                    replace(command, note=replace(command.note, body="# Different"))
                )
            update = replace(
                command,
                write_mode=ObsidianWriteMode.UPDATE,
                note=replace(
                    command.note,
                    body="# Updated",
                    idempotency_key="update-one",
                    expected_content_hash=outcome.content_hash,
                ),
            )
            updated = await service.write_note(update)
            await session.commit()
            assert (
                await outcomes.note_write_outcome("update-one")
            ).content_hash == updated.note.content_hash
            with pytest.raises(ObsidianWriteConflictError):
                await service.write_note(
                    replace(
                        update,
                        note=replace(
                            update.note,
                            body="# Stale",
                            idempotency_key="stale-one",
                            expected_content_hash=outcome.content_hash,
                        ),
                    )
                )
            assert (
                await outcomes.note_write_outcome("stale-one")
            ).status.value == "CONFLICTED"
            assert (
                await outcomes.note_write_outcome("never-admitted")
            ).status.value == "NOT_COMMITTED"
        finally:
            await session.close()
            await database.shutdown()

    asyncio.run(scenario())


def test_invalid_receipt_identity_and_started_evidence_fail_closed(
    tmp_path: Path,
) -> None:
    """Wrong-key, incomplete-started, and naive-time receipts require recovery."""

    async def scenario():
        database, session, service = await _services(tmp_path)
        vault = tmp_path / "vault"
        store = ObsidianReportBundleRunStore(vault_path=vault)
        vault_store = ObsidianVaultConfigStore(
            default_vault_path=str(vault),
            default_alexandria_root="Alexandria",
            config_path=None,
        )
        receipts = NoteMutationReceipts(vault_store)
        outcomes = ObsidianMutationOutcomeService(service, vault_store)

        def save_raw(key: str, record: JSONObject) -> None:
            store.save(
                note_mutation_id(key),
                {"kind": "note-write", "record": record},
            )

        try:
            save_raw(
                "wrong-key",
                {
                    "idempotency_key": "different-key",
                    "mutation_id": note_mutation_id("different-key"),
                    "operation_identity": "a" * 64,
                    "status": "NOT_COMMITTED",
                },
            )
            wrong_key = await outcomes.note_write_outcome("wrong-key")
            assert wrong_key.status.value == "RECONCILIATION_REQUIRED"

            save_raw(
                "incomplete-started",
                {
                    "idempotency_key": "incomplete-started",
                    "mutation_id": note_mutation_id("incomplete-started"),
                    "operation_identity": "b" * 64,
                    "status": "UNKNOWN",
                    "effect_started": True,
                    "canonical_path": "Alexandria/Job Plans/incomplete.md",
                    "note_id": None,
                    "expected_source_hash": None,
                },
            )
            incomplete = await outcomes.note_write_outcome("incomplete-started")
            assert incomplete.status.value == "RECONCILIATION_REQUIRED"

            save_raw(
                "naive-committed",
                {
                    "idempotency_key": "naive-committed",
                    "mutation_id": note_mutation_id("naive-committed"),
                    "operation_identity": "c" * 64,
                    "status": "COMMITTED",
                    "effect_started": True,
                    "canonical_path": "Alexandria/Job Plans/naive.md",
                    "note_id": "naive-note",
                    "expected_source_hash": "d" * 64,
                    "content_hash": "e" * 64,
                    "committed_at": "2026-09-30T00:00:00",
                },
            )
            naive = await outcomes.note_write_outcome("naive-committed")
            assert naive.status.value == "RECONCILIATION_REQUIRED"

            corrupt_path = store._path(note_mutation_id("corrupt"))
            corrupt_path.parent.mkdir(parents=True, exist_ok=True)
            corrupt_path.write_text("{not-json", encoding="utf-8")
            corrupt = await outcomes.note_write_outcome("corrupt")
            assert corrupt.status.value == "RECONCILIATION_REQUIRED"

            command = ObsidianWriteNote(
                note=ObsidianSaveNote(
                    title="Blocked",
                    body="# Must not write",
                    alexandria_type=AlexandriaNoteType.JOB_PLAN,
                    relative_path="Alexandria/Job Plans/blocked.md",
                    idempotency_key="incomplete-started",
                ),
                write_mode=ObsidianWriteMode.CREATE,
                match_by=ObsidianWriteMatchBy.PATH,
            )
            with pytest.raises(ObsidianCheckpointRecoveryRequiredError):
                await service.write_note(command)
            assert command.note.relative_path is not None
            assert not (vault / command.note.relative_path).exists()

            with pytest.raises(ObsidianValidationError):
                await receipts.load_by_mutation_id("note-write:" + "f" * 63 + "g")
        finally:
            await session.close()
            await database.shutdown()

    asyncio.run(scenario())


def test_source_commit_with_pipeline_failure_is_read_back_once_and_never_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A filesystem response failure cannot trigger another canonical write."""
    import app.obsidian.application.service.notes.obsidian_note_service as write_module

    real_write = write_module.atomic_write_markdown
    writes: list[bytes] = []

    def lost_response(path: Path, content: str) -> None:
        real_write(path, content)
        writes.append(path.read_bytes())
        raise OSError("filesystem result lost after replace")

    monkeypatch.setattr(write_module, "atomic_write_markdown", lost_response)

    async def scenario():
        database, session, service = await _services(tmp_path)
        outcomes = ObsidianMutationOutcomeService(
            service,
            ObsidianVaultConfigStore(
                default_vault_path=str(tmp_path / "vault"),
                default_alexandria_root="Alexandria",
                config_path=None,
            ),
        )
        command = ObsidianWriteNote(
            note=ObsidianSaveNote(
                title="Lost",
                body="# Lost response",
                alexandria_type=AlexandriaNoteType.JOB_PLAN,
                relative_path="Alexandria/Job Plans/Lost.md",
                idempotency_key="lost-one",
            ),
            write_mode=ObsidianWriteMode.CREATE,
            match_by=ObsidianWriteMatchBy.PATH,
        )
        try:
            with pytest.raises(OSError):
                await service.write_note(command)
            assert (
                await outcomes.note_write_outcome("lost-one")
            ).status.value == "COMMITTED"
            result = await service.write_note(command)
            assert command.note.relative_path is not None
            assert result.storage_status == "unchanged"
            assert result.fts_status == "unknown"
            assert result.reindex_required is True
            assert "mutation_pipeline_reconciliation_required" in result.warnings
            assert len(writes) == 1
            (tmp_path / "vault" / command.note.relative_path).unlink()
            assert (
                await outcomes.note_write_outcome("lost-one")
            ).status.value == "UNKNOWN"
            with pytest.raises(ObsidianCheckpointRecoveryRequiredError):
                await service.write_note(command)
            assert len(writes) == 1
        finally:
            await session.close()
            await database.shutdown()

    asyncio.run(scenario())
