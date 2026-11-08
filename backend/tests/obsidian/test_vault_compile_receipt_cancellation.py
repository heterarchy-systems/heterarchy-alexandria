"""Compile evidence must finish before a cancelled reindex releases its lease."""

from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from pathlib import Path

import pytest

from app.obsidian.application.vault.vault_lifecycle_service import (
    ObsidianVaultLifecycleService,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianCompiledDocumentState,
    ObsidianSaveNote,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.types.extra_types import JSONObject


class _EmptyIndex:
    async def list_compiled_document_states(
        self,
    ) -> tuple[ObsidianCompiledDocumentState, ...]:
        return ()

    async def mark_documents_stale(self, paths: tuple[str, ...]) -> int:
        assert paths == ()
        return 0


async def _unexpected_save(payload: ObsidianSaveNote) -> ObsidianNote:
    raise AssertionError("An empty reindex must not save a source note")


async def _unexpected_read(path: str) -> ObsidianNote:
    raise AssertionError("An empty reindex must not read a source note")


async def _unexpected_supersession(
    superseded_context_id: str, replacement_context_id: str
) -> None:
    raise AssertionError("An empty reindex must not supersede a source note")


def test_compile_receipt_save_is_owned_until_cancelled_reindex_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        (tmp_path / "Alexandria").mkdir()
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        entered = asyncio.Event()
        release = threading.Event()
        original_save = ObsidianReportBundleRunStore.save

        def gated_save(
            store: ObsidianReportBundleRunStore, key: str, payload: JSONObject
        ) -> None:
            if key == "compile-receipt:latest":
                assert threading.get_ident() != loop_thread, (
                    "compile receipt save ran on the event-loop thread"
                )
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(timeout=5), (
                    "Compile receipt worker was not released"
                )
            original_save(store, key, payload)

        monkeypatch.setattr(ObsidianReportBundleRunStore, "save", gated_save)
        config = ObsidianVaultConfigStore(
            default_vault_path=str(tmp_path),
            default_alexandria_root="Alexandria",
            config_path=None,
        )
        coordinator = IndexMaintenanceCoordinator()
        service = ObsidianVaultLifecycleService(
            repository=_EmptyIndex(),
            vault_config_store=config,
            save_note=_unexpected_save,
            read_note_by_path=_unexpected_read,
            note_id_from_existing_file=lambda path: None,
            mark_context_superseded=_unexpected_supersession,
            context_reindex_hook=None,
            index_maintenance_coordinator=coordinator,
        )
        operation = asyncio.create_task(service.reindex())
        worker_entered = asyncio.create_task(entered.wait())
        contender_entered = asyncio.Event()
        contender_attempted = asyncio.Event()
        tasks = [operation, worker_entered]

        async def contend() -> None:
            contender_attempted.set()
            async with coordinator.operation("contending_reindex", wait=True):
                contender_entered.set()

        try:
            completed, _ = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED, timeout=5
            )
            if operation in completed:
                await operation
            assert worker_entered in completed
            operation.cancel()
            await asyncio.sleep(0)
            operation.cancel()
            await asyncio.sleep(0)
            assert not operation.done()
            assert coordinator.active_operation == "vault_reindex"

            contender = asyncio.create_task(contend())
            tasks.append(contender)
            await contender_attempted.wait()
            await asyncio.sleep(0)
            assert not contender_entered.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await operation
            await contender
            assert contender_entered.is_set()
            assert coordinator.active_operation is None
            receipt = ObsidianReportBundleRunStore(tmp_path).load(
                "compile-receipt:latest"
            )
            assert receipt is not None
            assert set(receipt) == {
                "plan_fingerprint",
                "policy_version",
                "applied_at",
                "changed_documents",
                "removed_documents",
                "embedding_invalidated_documents",
                "diagnostic_count",
            }
            assert receipt["changed_documents"] == 0
            assert receipt["removed_documents"] == 0
            assert receipt["diagnostic_count"] == 0
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, Exception):
                    await task

    asyncio.run(scenario())
