"""Cancellation ownership for public MemoryCycle checkpoint writes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Lock

import pytest
from pydantic import TypeAdapter
from tests.memory.reconciliation import test_memory_cycle_service as cycle_fixtures

from app.memory.domain.entities.memory_cycle import MemoryCycleCheckpoint
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleCheckpointState,
    MemoryCycleOperation,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)


def test_raw_repeated_cancellation_keeps_cycle_lease_until_checkpoint_save_drains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled apply retains its exclusive lease until its admitted save ends."""

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        save_started = asyncio.Event()
        save_finished = asyncio.Event()
        release_save = Event()
        first_save_lock = Lock()
        event_lock = Lock()
        timeline: list[str] = []
        blocked_admission_claimed = False

        def record(event: str) -> None:
            with event_lock:
                timeline.append(event)

        coordinators: list[IndexMaintenanceCoordinator] = []

        class TrackingCoordinator(IndexMaintenanceCoordinator):
            """Record lease release while retaining the real coordinator behavior."""

            def __init__(self) -> None:
                super().__init__()
                coordinators.append(self)

            @asynccontextmanager
            async def operation(
                self,
                name: str,
                wait: bool = False,
            ) -> AsyncGenerator[None]:
                async with super().operation(name=name, wait=wait):
                    try:
                        yield
                    finally:
                        record("lease-exit")

        monkeypatch.setattr(
            cycle_fixtures,
            "IndexMaintenanceCoordinator",
            TrackingCoordinator,
        )

        original_save_typed = ObsidianReportBundleRunStore.save_typed

        def gated_save_typed(
            store: ObsidianReportBundleRunStore,
            idempotency_key: str,
            record_value: MemoryCycleCheckpoint,
            adapter: TypeAdapter[MemoryCycleCheckpoint],
        ) -> None:
            nonlocal blocked_admission_claimed
            should_block = False
            if record_value.state is MemoryCycleCheckpointState.ADMITTED:
                with first_save_lock:
                    if not blocked_admission_claimed:
                        blocked_admission_claimed = True
                        should_block = True
            if should_block:
                loop.call_soon_threadsafe(save_started.set)
                if not release_save.wait(timeout=5):
                    raise TimeoutError(
                        "test did not release the admitted checkpoint save"
                    )
            try:
                original_save_typed(
                    store,
                    idempotency_key,
                    record_value,
                    adapter,
                )
            finally:
                if should_block:
                    record("admitted-save-finished")
                    loop.call_soon_threadsafe(save_finished.set)

        monkeypatch.setattr(
            ObsidianReportBundleRunStore,
            "save_typed",
            gated_save_typed,
        )

        service, _, _, _ = cycle_fixtures._service(tmp_path, cycle_fixtures._preview())
        coordinator = coordinators[0]
        preview = await service.execute(
            cycle_fixtures._request(MemoryCycleOperation.DRY_RUN)
        )
        request = cycle_fixtures._request(
            MemoryCycleOperation.APPLY,
            expected_plan_hash=preview.plan_hash,
        )

        apply_task: asyncio.Task[object] | None = None
        task_pending_while_blocked = False
        lease_held_while_blocked = False
        cancellation_propagated = False
        try:
            apply_task = asyncio.create_task(service.execute(request))
            async with asyncio.timeout(5):
                await save_started.wait()

            assert coordinator.active_operation == "memory_cycle"
            apply_task.cancel()
            await asyncio.sleep(0)
            apply_task.cancel()
            await asyncio.sleep(0)

            task_pending_while_blocked = not apply_task.done()
            lease_held_while_blocked = coordinator.active_operation == "memory_cycle"

            release_save.set()
            try:
                async with asyncio.timeout(5):
                    await apply_task
            except asyncio.CancelledError:
                cancellation_propagated = True

            async with asyncio.timeout(5):
                await save_finished.wait()
        finally:
            release_save.set()
            if apply_task is not None:
                if not apply_task.done():
                    apply_task.cancel()
                try:
                    async with asyncio.timeout(5):
                        await apply_task
                except asyncio.CancelledError:
                    pass
            if blocked_admission_claimed:
                async with asyncio.timeout(5):
                    await save_finished.wait()

        persisted = ObsidianReportBundleRunStore(tmp_path).load_typed(
            "memory-cycle:cycle-test",
            TypeAdapter(MemoryCycleCheckpoint),
        )
        assert persisted is not None
        assert persisted.state is MemoryCycleCheckpointState.ADMITTED
        assert task_pending_while_blocked
        assert lease_held_while_blocked
        assert cancellation_propagated
        assert timeline.index("admitted-save-finished") < timeline.index("lease-exit")

    asyncio.run(scenario())
