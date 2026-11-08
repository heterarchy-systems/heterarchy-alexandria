from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.obsidian.application.notes.report_bundles.obsidian_report_bundle_service import (
    ObsidianReportBundleService,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianReportBundleOwner,
    ObsidianReportBundleRequest,
    ObsidianReportBundleVerify,
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianNoteWriteResult,
    ObsidianReportBundleResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
    ObsidianWriteOperation,
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
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianStoredProjectionError,
)

_FIXED_TIME = datetime(2026, 11, 7, tzinfo=UTC)


def _note(
    note_id: str,
    relative_path: str,
    *,
    body: str = "body",
    index_status: ObsidianIndexStatus = ObsidianIndexStatus.INDEXED,
) -> ObsidianNote:
    return ObsidianNote(
        note_id=note_id,
        relative_path=relative_path,
        alexandria_type=AlexandriaNoteType.JOB_PLAN,
        title=note_id,
        status="active",
        tags=(),
        project=None,
        source=None,
        content_hash=f"{note_id}-hash",
        frontmatter={"content_hash": f"{note_id}-hash"},
        body=body,
        index_status=index_status,
        error_message=None,
        size_bytes=len(body.encode("utf-8")),
        modified_at=_FIXED_TIME,
        indexed_at=_FIXED_TIME if index_status is ObsidianIndexStatus.INDEXED else None,
    )


class _RunObservation:
    def __init__(self, coordinator: IndexMaintenanceCoordinator) -> None:
        self.coordinator = coordinator
        self.task: asyncio.Task[object] | None = None
        self.events: list[str] = []

    def check(self, event: str) -> None:
        assert asyncio.current_task() is self.task
        assert self.coordinator.active_operation == "obsidian_report_bundle"
        self.events.append(event)


class _BundleNotes:
    def __init__(
        self,
        vault_path: Path,
        observation: _RunObservation,
        *,
        failure_path: str | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.observation = observation
        self.failure_path = failure_path
        self.write_paths: list[str] = []
        self.stored_error: ObsidianStoredProjectionError | None = None
        self.notes: dict[str, ObsidianNote] = {}
        owner = _note("report-owner", "Alexandria/owner.md")
        self.notes[owner.note_id] = owner

    async def read_note_by_path(self, relative_path: str) -> ObsidianNote:
        self.observation.check("read_note_by_path")
        for note in self.notes.values():
            if note.relative_path == relative_path:
                return note
        raise ObsidianNotFoundError(relative_path)

    async def read_note(self, note_id: str) -> ObsidianNote:
        self.observation.check("read_note")
        try:
            return self.notes[note_id]
        except KeyError as error:
            raise ObsidianNotFoundError(note_id) from error

    async def write_note(self, command: ObsidianWriteNote) -> ObsidianNoteWriteResult:
        self.observation.check("write_note")
        relative_path = command.note.relative_path
        assert relative_path is not None
        self.write_paths.append(relative_path)
        source_path = self.vault_path / relative_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(command.note.body.encode("utf-8"))

        note_id = command.note.note_id or "report-source"
        note = _note(
            note_id,
            relative_path,
            body=command.note.body,
            index_status=ObsidianIndexStatus.UNINDEXED,
        )
        self.notes[note_id] = note
        if relative_path == self.failure_path:
            self.stored_error = ObsidianStoredProjectionError(
                note,
                failed_stage="metadata_index",
            )
            raise self.stored_error

        return ObsidianNoteWriteResult(
            operation=ObsidianWriteOperation.CREATED,
            write_mode=command.write_mode,
            match_by=command.match_by,
            note=note,
            storage_status="saved",
            metadata_status="indexed",
            fts_status="indexed",
            graph_edge_index_status="indexed",
            graph_projection_status="stale",
            reindex_required=True,
        )

    async def source_snapshot(self, max_notes: int) -> SimpleNamespace:
        self.observation.check("source_snapshot")
        raise AssertionError("duplicate source snapshot is disabled in this test")


class _Reindex:
    def __init__(self, notes: _BundleNotes) -> None:
        self.notes = notes
        self.calls = 0

    async def rebuild(self) -> SimpleNamespace:
        self.notes.observation.check("rebuild")
        self.calls += 1
        self.notes.notes["report-source"] = _note(
            "report-source",
            "Alexandria/source.md",
            body=self.notes.notes["report-source"].body,
            index_status=ObsidianIndexStatus.INDEXED,
        )
        return SimpleNamespace(
            graph_projection=SimpleNamespace(status="completed", issue_total=0)
        )


class _Graph:
    def __init__(self, observation: _RunObservation) -> None:
        self.observation = observation

    async def related_notes(self, note_id: str, limit: int) -> list[object]:
        self.observation.check("related_notes")
        return []


def _request(
    idempotency_key: str,
    *,
    owners: tuple[ObsidianReportBundleOwner, ...] = (),
    verify: ObsidianReportBundleVerify | None = None,
) -> ObsidianReportBundleRequest:
    return ObsidianReportBundleRequest(
        idempotency_key=idempotency_key,
        source=ObsidianSaveNote(
            title="Report source",
            body="# Report source\n",
            relative_path="source.md",
            alexandria_type=AlexandriaNoteType.JOB_PLAN,
        ),
        graph_owners=owners,
        verify=verify or ObsidianReportBundleVerify(),
    )


def _service(
    vault_path: Path,
    coordinator: IndexMaintenanceCoordinator,
    observation: _RunObservation,
    *,
    failure_path: str | None = None,
) -> tuple[ObsidianReportBundleService, _BundleNotes, _Reindex]:
    notes = _BundleNotes(vault_path, observation, failure_path=failure_path)
    reindex = _Reindex(notes)
    config = ObsidianVaultConfigStore(
        default_vault_path=str(vault_path),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    service = ObsidianReportBundleService(
        obsidian_service=notes,
        vault_reindex_service=reindex,
        graph_service=_Graph(observation),
        vault_config_store=config,
        index_maintenance_coordinator=coordinator,
    )
    return service, notes, reindex


@pytest.mark.parametrize("failure_site", ["source", "owner"])
def test_stored_projection_errors_escape_without_false_checkpoint(
    tmp_path: Path,
    failure_site: str,
) -> None:
    asyncio.run(_stored_projection_error_scenario(tmp_path, failure_site))


async def _stored_projection_error_scenario(
    tmp_path: Path,
    failure_site: str,
) -> None:
    coordinator = IndexMaintenanceCoordinator()
    observation = _RunObservation(coordinator)
    failed_path = f"Alexandria/{failure_site}.md"
    service, notes, reindex = _service(
        tmp_path,
        coordinator,
        observation,
        failure_path=failed_path,
    )
    owners = (
        (ObsidianReportBundleOwner(path="owner.md"),) if failure_site == "owner" else ()
    )
    request = _request(f"stored-projection-{failure_site}", owners=owners)
    operation = asyncio.create_task(service.upsert(request))
    observation.task = operation

    with pytest.raises(ObsidianStoredProjectionError) as raised:
        await operation

    assert notes.stored_error is not None
    assert raised.value is notes.stored_error
    assert raised.value.note.relative_path == failed_path
    assert (tmp_path / "Alexandria/source.md").read_bytes() == b"# Report source\n"
    if failure_site == "owner":
        assert (tmp_path / "Alexandria/owner.md").read_bytes() == b"body"
        assert notes.write_paths == ["Alexandria/source.md", "Alexandria/owner.md"]
    else:
        assert notes.write_paths == ["Alexandria/source.md"]
    assert reindex.calls == 0
    assert (
        ObsidianReportBundleRunStore(vault_path=tmp_path).load(request.idempotency_key)
        is None
    )
    assert coordinator.active_operation is None


def test_checkpoint_io_is_worker_owned_and_cancelled_save_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_checkpoint_io_cancellation_scenario(tmp_path, monkeypatch))


async def _checkpoint_io_cancellation_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    loop_thread_id = threading.get_ident()
    load_started = asyncio.Event()
    release_load = threading.Event()
    save_started = asyncio.Event()
    release_save = threading.Event()
    load_threads: list[int] = []
    save_threads: list[int] = []
    gated_loads = 0
    read_checkpoint = ObsidianReportBundleRunStore._read_checkpoint
    fsync_root = ObsidianReportBundleRunStore._fsync_root

    def gated_read_checkpoint(
        store: ObsidianReportBundleRunStore,
        idempotency_key: str,
    ) -> bytes | None:
        nonlocal gated_loads
        thread_id = threading.get_ident()
        load_threads.append(thread_id)
        if gated_loads == 0:
            gated_loads += 1
            loop.call_soon_threadsafe(load_started.set)
            if thread_id == loop_thread_id:
                raise AssertionError("checkpoint load ran on the event-loop thread")
            if not release_load.wait(timeout=5):
                raise AssertionError("test did not release the checkpoint load")
        return read_checkpoint(store, idempotency_key)

    def gated_fsync_root(store: ObsidianReportBundleRunStore) -> None:
        thread_id = threading.get_ident()
        save_threads.append(thread_id)
        loop.call_soon_threadsafe(save_started.set)
        if thread_id == loop_thread_id:
            raise AssertionError("checkpoint save ran on the event-loop thread")
        if not release_save.wait(timeout=5):
            raise AssertionError("test did not release the checkpoint save")
        fsync_root(store)

    monkeypatch.setattr(
        ObsidianReportBundleRunStore,
        "_read_checkpoint",
        gated_read_checkpoint,
    )
    monkeypatch.setattr(
        ObsidianReportBundleRunStore,
        "_fsync_root",
        gated_fsync_root,
    )

    coordinator = IndexMaintenanceCoordinator()
    observation = _RunObservation(coordinator)
    service, notes, reindex = _service(tmp_path, coordinator, observation)
    request = _request(
        "checkpoint-worker-cancel",
        verify=ObsidianReportBundleVerify(
            index_status=False,
            incoming_edges=False,
            duplicates=False,
        ),
    )
    operation = asyncio.create_task(service.upsert(request))
    observation.task = operation
    competitor_attempted = asyncio.Event()
    competitor_entered = asyncio.Event()
    release_competitor = asyncio.Event()

    async def wait_for_bundle_lease() -> None:
        competitor_attempted.set()
        async with coordinator.operation("concurrent_report_bundle", wait=True):
            competitor_entered.set()
            await release_competitor.wait()

    competitor: asyncio.Task[None] | None = None
    retry: asyncio.Task[ObsidianReportBundleResult] | None = None
    heartbeat_tasks: list[asyncio.Task[None]] = []

    async def pulse(signal: asyncio.Event) -> None:
        signal.set()

    try:
        await asyncio.wait_for(load_started.wait(), timeout=3)
        assert load_threads[-1] != loop_thread_id
        load_heartbeat = asyncio.Event()
        heartbeat_tasks.append(asyncio.create_task(pulse(load_heartbeat)))
        await asyncio.wait_for(load_heartbeat.wait(), timeout=3)
        assert not operation.done()
        release_load.set()

        await asyncio.wait_for(save_started.wait(), timeout=3)
        assert save_threads[-1] != loop_thread_id
        save_heartbeat = asyncio.Event()
        heartbeat_tasks.append(asyncio.create_task(pulse(save_heartbeat)))
        await asyncio.wait_for(save_heartbeat.wait(), timeout=3)
        assert coordinator.active_operation == "obsidian_report_bundle"
        assert notes.write_paths == ["Alexandria/source.md"]
        assert reindex.calls == 1

        operation.cancel()
        operation.cancel()
        competitor = asyncio.create_task(wait_for_bundle_lease())
        await asyncio.wait_for(competitor_attempted.wait(), timeout=3)
        assert not operation.done()
        assert operation.cancelling() >= 1
        assert coordinator.active_operation == "obsidian_report_bundle"
        assert not competitor_entered.is_set()

        release_save.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(operation, timeout=3)
        await asyncio.wait_for(competitor_entered.wait(), timeout=3)
        assert coordinator.active_operation == "concurrent_report_bundle"
        release_competitor.set()
        await asyncio.wait_for(competitor, timeout=3)
        competitor = None
        assert coordinator.active_operation is None

        retry = asyncio.create_task(service.upsert(request))
        observation.task = retry
        replay = await asyncio.wait_for(retry, timeout=3)
        assert replay.replayed is True
        assert notes.write_paths == ["Alexandria/source.md"]
        assert coordinator.active_operation is None
        assert all(thread_id != loop_thread_id for thread_id in load_threads)
        assert all(thread_id != loop_thread_id for thread_id in save_threads)
    finally:
        release_load.set()
        release_save.set()
        release_competitor.set()
        for heartbeat_task in heartbeat_tasks:
            await asyncio.wait_for(heartbeat_task, timeout=5)
        if not operation.done():
            operation.cancel()
        try:
            await asyncio.wait_for(operation, timeout=5)
        except asyncio.CancelledError:
            pass
        except AssertionError as error:
            assert str(error) in {
                "checkpoint load ran on the event-loop thread",
                "checkpoint save ran on the event-loop thread",
            }
        if retry is not None:
            if not retry.done():
                retry.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(retry, timeout=5)
        if competitor is not None:
            if not competitor.done():
                competitor.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(competitor, timeout=5)
