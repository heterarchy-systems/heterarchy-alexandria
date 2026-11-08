"""Orphan evidence writes retain their lease until the worker drains."""

from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from pathlib import Path

import pytest

from app.obsidian.application.graph.diagnostics.obsidian_graph_orphan_census_service import (
    ObsidianGraphOrphanCensusService,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianReadPort
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionNode,
    ObsidianGraphProjectionState,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.graph.native_obsidian_graph_diagnostics_compute_provider import (
    create_native_obsidian_graph_diagnostics_compute_provider,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)


class _Projection:
    async def state(self) -> ObsidianGraphProjectionState:
        return ObsidianGraphProjectionState(
            initialized=True,
            run_id="run-a",
            projection=ObsidianGraphProjection(
                nodes=(
                    ObsidianGraphProjectionNode(
                        note_id="orphan-a",
                        relative_path="Alexandria/a.md",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        title="A",
                        status="active",
                        project=None,
                    ),
                )
            ),
        )


class _UnusedSource(ObsidianReadPort):
    async def read_note(self, note_id: str) -> ObsidianNote:
        raise AssertionError("Census persistence must not read source notes")

    async def read_note_by_path(self, relative_path: str) -> ObsidianNote:
        raise AssertionError("Census persistence must not read source notes")


@pytest.mark.parametrize("kind", ["ack", "census"])
def test_cancelled_orphan_save_finishes_before_lease_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = threading.Event()
        finished = threading.Event()
        original_fsync = ObsidianReportBundleRunStore._fsync_root

        def gated_fsync(store: ObsidianReportBundleRunStore) -> None:
            loop.call_soon_threadsafe(entered.set)
            try:
                assert release.wait(timeout=5), "Orphan write worker was not released"
                original_fsync(store)
            finally:
                finished.set()

        monkeypatch.setattr(ObsidianReportBundleRunStore, "_fsync_root", gated_fsync)
        config = ObsidianVaultConfigStore(
            default_vault_path=str(tmp_path),
            default_alexandria_root="Alexandria",
            config_path=None,
        )
        coordinator = IndexMaintenanceCoordinator()
        service = ObsidianGraphOrphanCensusService(
            graph_repository=_Projection(),
            vault_config_store=config,
            compute_provider=create_native_obsidian_graph_diagnostics_compute_provider(),
            index_maintenance_coordinator=coordinator,
            source_reader=_UnusedSource(),
        )
        operation = asyncio.create_task(
            service.acknowledge_orphan(
                note_id="orphan-a", decision="ACKNOWLEDGED_STANDALONE"
            )
            if kind == "ack"
            else service.list_orphans()
        )
        tasks = [operation]
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            operation.cancel()
            await asyncio.sleep(0)
            operation.cancel()
            await asyncio.sleep(0)
            assert not operation.done(), (
                "Orphan save released before its worker finished"
            )
            expected_lease = (
                "obsidian_orphan_acknowledgement"
                if kind == "ack"
                else "obsidian_orphan_census"
            )
            assert coordinator.active_operation == expected_lease
            contender_attempted = asyncio.Event()
            contender_entered = asyncio.Event()

            async def contend() -> None:
                contender_attempted.set()
                async with coordinator.operation("next_orphan_operation", wait=True):
                    contender_entered.set()

            contender = asyncio.create_task(contend())
            tasks.append(contender)
            await contender_attempted.wait()
            await asyncio.sleep(0)
            assert not contender_entered.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await operation
            await contender
            assert finished.is_set()
            assert contender_entered.is_set()
            assert coordinator.active_operation is None
            prefix = "orphan-ack:" if kind == "ack" else "orphan-census:"
            saved = ObsidianReportBundleRunStore(tmp_path).load(prefix + "orphan-a")
            assert saved is not None
            assert saved["record"]["note_id"] == "orphan-a"
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, Exception):
                    await task
            await asyncio.to_thread(finished.wait, 5)

    asyncio.run(scenario())
