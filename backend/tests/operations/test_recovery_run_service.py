"""PostgreSQL-native recovery run lifecycle tests."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Event as ThreadEvent, Lock
from types import SimpleNamespace

import anyio
import pytest
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService

from app.operations.application.recovery.execution import recovery_run_manifest
from app.operations.application.recovery.execution.recovery_run_errors import (
    RecoveryInProgressError,
    RecoveryRunNotRetryableError,
    RecoveryRunObservationUnavailableError,
)
from app.operations.application.recovery.execution.recovery_run_manifest import (
    RecoveryActiveLockStore,
    active_lock_path,
    manifest_path_by_id,
)
from app.operations.application.recovery.execution.recovery_run_service import (
    RecoveryRunService,
)
from app.operations.application.recovery.planning.recovery_plan_contracts import (
    RecoveryPlanRequest,
)
from app.operations.application.recovery.planning.recovery_plan_service import (
    RecoveryPlanService,
)
from app.operations.domain.entities.recovery_plan import (
    RecoveryPlan,
    RecoveryPlanStep,
    RecoverySourceSnapshot,
)
from app.operations.domain.entities.recovery_run import RecoveryRun
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)
from app.operations.domain.event_enum.operational_recovery_enums import (
    RecoveryRunStatus,
)


class _FakeContextService:
    pass


class _FakeDatabase:
    """Request-session boundary standing in for the shared database."""

    @asynccontextmanager
    async def request_session(self):
        class _Session:
            async def commit(self) -> None:
                return None

        yield _Session()


class _FakeObsidianService:
    async def status(self) -> SimpleNamespace:
        return SimpleNamespace(vault_path="/vault", alexandria_root="Alexandria")


class _FakeRepairObsidianService(_FakeObsidianService):
    """Fake source that revalidates one note and fails the rest."""

    def __init__(self, failing_paths: set[str]) -> None:
        self.failing_paths = failing_paths
        self.revalidated: list[str] = []

    async def revalidate_note_index(self, *, path: str) -> SimpleNamespace:
        if path in self.failing_paths:
            raise ValueError(f"unparseable source: {path}")
        self.revalidated.append(path)
        return SimpleNamespace(note_id=f"note-{path}", content_hash="a" * 64)


class _FakeCompileObsidianService(_FakeObsidianService):
    async def reindex(self) -> SimpleNamespace:
        return SimpleNamespace(
            files_seen=1,
            files_indexed=1,
            files_skipped=0,
            stale_marked=0,
            errors=(),
            plan_fingerprint="a" * 64,
            policy_version="policy-current",
            embedding_invalidated_documents=0,
            diagnostic_count=0,
        )


class _PausedCompileObsidianService(_FakeCompileObsidianService):
    def __init__(
        self, effect_started: asyncio.Event, resume_effect: asyncio.Event
    ) -> None:
        self.effect_started = effect_started
        self.resume_effect = resume_effect
        self.status_reads = 0
        self.vault_path = "/vault"
        self.alexandria_root = "Alexandria"

    async def status(self) -> SimpleNamespace:
        self.status_reads += 1
        return SimpleNamespace(
            vault_path=self.vault_path,
            alexandria_root=self.alexandria_root,
        )

    async def reindex(self) -> SimpleNamespace:
        self.effect_started.set()
        await self.resume_effect.wait()
        return await super().reindex()


class _CountingCompileObsidianService(_FakeCompileObsidianService):
    def __init__(self) -> None:
        self.reindex_calls = 0

    async def reindex(self) -> SimpleNamespace:
        self.reindex_calls += 1
        return await super().reindex()


class _StatusCountingObsidianService(_FakeObsidianService):
    def __init__(self) -> None:
        self.status_reads = 0

    async def status(self) -> SimpleNamespace:
        self.status_reads += 1
        return await super().status()


def _files_under(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _plan(
    *, key: str, automatic: bool, steps: tuple[RecoveryPlanStep, ...]
) -> RecoveryPlan:
    source = RecoverySourceSnapshot(
        vault_path="/vault",
        alexandria_root="Alexandria",
        managed_markdown_count=1,
        representative_path="/vault/Alexandria/note.md",
        representative_sha256="abc",
        disk_free_bytes=1_000_000,
        markdown_manifest={"Alexandria/note.md": "1:1"},
    )
    return RecoveryPlan(
        id=f"run-{key}",
        parent_run_id=None,
        idempotency_key=key,
        trigger="manual",
        actor="test",
        status=OperationalReadinessStatus.RECOVERY_REQUIRED,
        created_at=datetime.now(UTC),
        dry_run=True,
        plan_hash="0" * 64,
        automatic_execution_allowed=automatic,
        diagnosis=("rag_fts_not_healthy",),
        blocked_reasons=() if automatic else ("postgresql_server_recovery_required",),
        source_snapshot=source,
        steps=steps,
        estimated_reindex_scope={},
        service_impact=("search_blocked_until_verify",),
        next_actions=("start_recovery_run",)
        if automatic
        else ("restore_postgresql_from_backup",),
        readiness=SimpleNamespace(),
        warnings=("rag_fts_not_healthy",),
    )


def _service(
    obsidian_service: _FakeObsidianService | None = None,
    **callbacks,
) -> RecoveryRunService:
    return RecoveryRunService(
        database=_FakeDatabase(),
        context_service=_FakeContextService(),
        obsidian_service=obsidian_service or _FakeObsidianService(),
        graph_projection_service=HealthyGraphProjectionService(),
        **callbacks,
    )


def test_blocked_plan_persists_blocked_run_without_mutation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = _plan(key="blocked", automatic=False, steps=())

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)

    async def scenario():
        return await _service().start(
            RecoveryPlanRequest(idempotency_key="blocked", expected_plan_hash="0" * 64)
        )

    run = anyio.run(scenario)
    assert run.status is RecoveryRunStatus.BLOCKED
    assert run.step_results == ()
    assert run.next_actions == ("restore_postgresql_from_backup",)


def test_snapshot_only_run_completes_and_is_idempotent(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="snapshot",
        automatic=True,
        steps=(
            RecoveryPlanStep(
                "snapshot_sources", "Snapshot source vault metadata", False
            ),
        ),
    )

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)

    async def scenario():
        service = _service()
        first = await service.start(
            RecoveryPlanRequest(idempotency_key="snapshot", expected_plan_hash="0" * 64)
        )
        second = await service.start(
            RecoveryPlanRequest(idempotency_key="snapshot", expected_plan_hash="0" * 64)
        )
        committed_manifest = Path(first.manifest_path).read_bytes()
        rejected = await service.start(
            RecoveryPlanRequest(idempotency_key="snapshot", expected_plan_hash="f" * 64)
        )
        assert rejected.error_code == "RECOVERY_PLAN_IDEMPOTENCY_CONFLICT"
        assert Path(first.manifest_path).read_bytes() == committed_manifest
        return first, second

    first, second = anyio.run(scenario)
    assert first.status is RecoveryRunStatus.COMPLETED
    assert [step.code for step in first.step_results] == ["snapshot_sources"]
    assert second == first


def test_healthy_no_repair_run_executes_only_source_snapshot_and_readiness_check(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A healthy plan completes without repair effects but performs a real check."""
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="healthy-no-op",
        automatic=True,
        steps=(
            RecoveryPlanStep("snapshot_sources", "Snapshot sources", False),
            RecoveryPlanStep("CURRENT_READINESS_CHECK", "Check readiness", False),
        ),
    )
    plan.plan_hash = "0" * 64

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)
    service = _service()
    calls: list[str] = []

    async def verify(plan, **kwargs):
        del plan, kwargs
        calls.append("readiness")
        return {"ready": True}

    monkeypatch.setattr(service._verification, "verify_readiness", verify)
    run = anyio.run(
        service.start,
        RecoveryPlanRequest(
            idempotency_key="healthy-no-op", expected_plan_hash="0" * 64
        ),
    )

    assert run.status is RecoveryRunStatus.COMPLETED
    assert calls == ["readiness"]
    assert [step.code for step in run.step_results] == [
        "snapshot_sources",
        "CURRENT_READINESS_CHECK",
    ]


def test_cause_specific_graph_link_and_dlq_steps_are_ordered_and_read_only(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Graph/link/DLQ callbacks run in order without retrying or creating effects."""
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="diagnostics",
        automatic=True,
        steps=(
            RecoveryPlanStep("GRAPH_REVALIDATE", "Graph", True),
            RecoveryPlanStep("LINK_REVALIDATE", "Links", False),
            RecoveryPlanStep("DLQ_RECONCILE", "DLQ", False),
            RecoveryPlanStep("CURRENT_READINESS_CHECK", "Readiness", False),
        ),
    )
    plan.plan_hash = "0" * 64

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)
    events: list[str] = []

    async def graph() -> dict[str, object]:
        events.append("graph")
        return {"status": "completed", "errors": []}

    async def links() -> dict[str, object]:
        events.append("links")
        return {"status": "checked", "issues": []}

    async def dlq() -> dict[str, object]:
        events.append("dlq")
        return {"status": "reconciled", "retryable": False, "ready": True}

    service = _service(
        graph_rebuild_callback=graph,
        link_diagnostics_callback=links,
        dlq_reconcile_callback=dlq,
    )

    async def verify(plan, **kwargs):
        del plan, kwargs
        events.append("readiness")
        return {"ready": True}

    monkeypatch.setattr(service._verification, "verify_readiness", verify)
    run = anyio.run(
        service.start,
        RecoveryPlanRequest(idempotency_key="diagnostics", expected_plan_hash="0" * 64),
    )

    assert run.status is RecoveryRunStatus.COMPLETED
    assert events == ["graph", "links", "dlq", "readiness"]


def test_bounded_embedding_callback_result_is_recorded_without_silent_continuation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The configured recovery owner returns bounded batch evidence verbatim."""
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="embedding-batches",
        automatic=True,
        steps=(
            RecoveryPlanStep("EMBEDDING_REINDEX", "Embeddings", True),
            RecoveryPlanStep("CURRENT_READINESS_CHECK", "Readiness", False),
        ),
    )
    plan.plan_hash = "0" * 64

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)
    captured: dict[str, int] = {}

    async def embeddings(service, batch_size, max_batches):
        del service
        captured.update(batch_size=batch_size, max_batches=max_batches)
        return {
            "scanned": 2000,
            "updated": 2000,
            "skipped": 0,
            "warnings": [],
            "batches": [
                {"batch": 1, "scanned": 1000, "updated": 1000},
                {"batch": 2, "scanned": 1000, "updated": 1000},
            ],
        }

    service = _service(
        embedding_recovery_callback=embeddings,
        embedding_batch_size=1000,
        embedding_max_batches=40,
    )

    async def verify(plan, **kwargs):
        del plan, kwargs
        return {"ready": True}

    monkeypatch.setattr(service._verification, "verify_readiness", verify)
    run = anyio.run(
        service.start,
        RecoveryPlanRequest(
            idempotency_key="embedding-batches", expected_plan_hash="0" * 64
        ),
    )

    assert run.status is RecoveryRunStatus.COMPLETED
    assert captured == {"batch_size": 1000, "max_batches": 40}
    assert run.rebuild_results["embeddings"]["batches"][1]["updated"] == 1000


def test_unsupported_recovery_step_fails_closed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="unsupported",
        automatic=True,
        steps=(
            RecoveryPlanStep("drop_database", "Unsupported destructive action", True),
        ),
    )

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)

    async def scenario():
        return await _service().start(
            RecoveryPlanRequest(
                idempotency_key="unsupported", expected_plan_hash="0" * 64
            )
        )

    run = anyio.run(scenario)
    assert run.status is RecoveryRunStatus.FAILED
    assert run.error_code == "UNSUPPORTED_RECOVERY_STEP"
    assert run.next_actions == ("inspect_recovery_run",)


def test_active_lock_rejects_second_recovery_start(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = _plan(key="locked", automatic=True, steps=())
    RecoveryActiveLockStore.write(plan)

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)

    async def scenario():
        with pytest.raises(RecoveryInProgressError) as raised:
            await _service().start(
                RecoveryPlanRequest(
                    idempotency_key="locked", expected_plan_hash="0" * 64
                )
            )
        return raised.value

    error = anyio.run(scenario)
    assert error.run_id == plan.id
    assert error.idempotency_key == plan.idempotency_key


def test_running_manifest_is_read_only_and_same_key_start_replays_it(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan_steps = (RecoveryPlanStep("VAULT_REINDEX", "Rebuild vault", True),)

    async def fake_plan(self, request: RecoveryPlanRequest) -> RecoveryPlan:
        del self
        return _plan(
            key=request.idempotency_key or "generated",
            automatic=True,
            steps=plan_steps,
        )

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)
    start_request = RecoveryPlanRequest(
        idempotency_key="in-flight", expected_plan_hash="0" * 64
    )

    async def scenario() -> tuple[RecoveryRun, RecoveryRun, RecoveryRun | None]:
        effect_started = asyncio.Event()
        resume_effect = asyncio.Event()
        obsidian_service = _PausedCompileObsidianService(effect_started, resume_effect)
        service = _service(obsidian_service)
        completed_runs: dict[str, RecoveryRun] = {}

        async def execute() -> None:
            completed_runs["run"] = await service.start(start_request)

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(execute)
            await effect_started.wait()

            manifest_path = manifest_path_by_id(run_id="run-in-flight")
            recovery_root = manifest_path.parents[1]
            active_path = active_lock_path()
            before_files = _files_under(recovery_root)
            before_manifest = manifest_path.read_bytes()
            before_active = active_path.read_bytes()

            obsidian_service.vault_path = "/changed-vault"
            obsidian_service.alexandria_root = "ChangedRoot"
            for _ in range(2):
                observed = await service.get("run-in-flight")
                assert observed is not None
                assert observed.status is RecoveryRunStatus.RUNNING
                assert observed.source_snapshot.vault_path == "/vault"
                assert observed.source_snapshot.alexandria_root == "Alexandria"
                assert await service.start(start_request) == observed
                assert _files_under(recovery_root) == before_files

            with pytest.raises(RecoveryRunNotRetryableError):
                await service.retry(
                    "run-in-flight",
                    RecoveryPlanRequest(idempotency_key="retry-running"),
                )
            with pytest.raises(RecoveryInProgressError):
                await service.start(
                    RecoveryPlanRequest(
                        idempotency_key="competing", expected_plan_hash="0" * 64
                    )
                )

            assert manifest_path.read_bytes() == before_manifest
            assert active_path.read_bytes() == before_active
            assert _files_under(recovery_root) == before_files
            assert obsidian_service.status_reads == 0
            resume_effect.set()

        completed = completed_runs["run"]
        final_replay = await service.start(start_request)
        unknown = await service.get("unknown-run")
        return completed, final_replay, unknown

    completed, final_replay, unknown = anyio.run(scenario)
    assert completed.status is RecoveryRunStatus.COMPLETED
    assert RecoveryActiveLockStore.read() is None
    assert final_replay == completed
    assert unknown is None


def test_same_key_waiter_replays_owner_result_after_guard_delay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    steps = (RecoveryPlanStep("VAULT_REINDEX", "Rebuild vault", True),)
    obsidian_service = _CountingCompileObsidianService()
    service = _service(obsidian_service)
    request = RecoveryPlanRequest(
        idempotency_key="same-key-race", expected_plan_hash="0" * 64
    )

    async def fake_plan(self, plan_request: RecoveryPlanRequest) -> RecoveryPlan:
        del self
        return _plan(
            key=plan_request.idempotency_key or "generated",
            automatic=True,
            steps=steps,
        )

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)
    waiting_b_at_guard = ThreadEvent()
    resume_b = ThreadEvent()
    guard_call_lock = Lock()
    guard_call_count = 0
    original_guard = recovery_run_manifest._active_record_guard

    @contextmanager
    def delay_first_guard() -> Generator[None]:
        nonlocal guard_call_count
        with guard_call_lock:
            delay = guard_call_count == 0
            guard_call_count += 1
        if delay:
            waiting_b_at_guard.set()
            if not resume_b.wait(timeout=10):
                raise TimeoutError("second recovery did not release the guard wait")
        with original_guard():
            yield

    monkeypatch.setattr(
        recovery_run_manifest,
        "_active_record_guard",
        delay_first_guard,
    )
    results: dict[str, RecoveryRun] = {}

    async def execute_b() -> None:
        results["b"] = await service.start(request)

    async def scenario() -> tuple[RecoveryRun, bytes]:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(execute_b)
            if not await asyncio.to_thread(waiting_b_at_guard.wait, 10):
                raise TimeoutError("second recovery did not reach the guard")

            try:
                owner_run = await service.start(request)
                assert owner_run.status is RecoveryRunStatus.COMPLETED
                assert RecoveryActiveLockStore.read() is None
                manifest_path = manifest_path_by_id(owner_run.id)
                owner_manifest = manifest_path.read_bytes()
            finally:
                resume_b.set()
        return owner_run, owner_manifest

    owner_run, owner_manifest = anyio.run(scenario)
    replay = results["b"]
    manifest_path = manifest_path_by_id(owner_run.id)
    assert replay == owner_run
    assert obsidian_service.reindex_calls == 1
    assert manifest_path.read_bytes() == owner_manifest


def test_start_cleans_active_lock_when_manifest_fsync_fails_after_replace(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="initial-write-failure",
        automatic=True,
        steps=(RecoveryPlanStep("VAULT_REINDEX", "Rebuild vault", True),),
    )
    obsidian_service = _CountingCompileObsidianService()

    async def fake_plan(self, request: RecoveryPlanRequest) -> RecoveryPlan:
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)
    manifest_path = manifest_path_by_id(plan.id)
    sync_directory = recovery_run_manifest._sync_recovery_directory

    def fail_manifest_directory_sync(path: Path) -> None:
        if path == manifest_path.parent:
            raise OSError("simulated initial manifest publication failure")
        sync_directory(path)

    monkeypatch.setattr(
        recovery_run_manifest,
        "_sync_recovery_directory",
        fail_manifest_directory_sync,
    )
    service = _service(obsidian_service)

    async def scenario() -> None:
        with pytest.raises(
            OSError, match="simulated initial manifest publication failure"
        ):
            await service.start(
                RecoveryPlanRequest(
                    idempotency_key="initial-write-failure",
                    expected_plan_hash="0" * 64,
                )
            )

    anyio.run(scenario)

    assert RecoveryActiveLockStore.read() is None
    assert not active_lock_path().exists()
    assert not manifest_path_by_id(plan.id).exists()
    assert anyio.run(service.get, plan.id) is None
    assert obsidian_service.reindex_calls == 0


def test_uncertain_final_manifest_publication_keeps_active_admission(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="final-write-failure",
        automatic=True,
        steps=(RecoveryPlanStep("VAULT_REINDEX", "Rebuild vault", True),),
    )
    obsidian_service = _CountingCompileObsidianService()

    async def fake_plan(self, request: RecoveryPlanRequest) -> RecoveryPlan:
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)
    manifest_path = manifest_path_by_id(plan.id)
    sync_directory = recovery_run_manifest._sync_recovery_directory
    manifest_directory_syncs = 0

    def fail_final_manifest_directory_sync(path: Path) -> None:
        nonlocal manifest_directory_syncs
        if path == manifest_path.parent:
            manifest_directory_syncs += 1
            if manifest_directory_syncs == 2:
                raise OSError("simulated final manifest publication failure")
        sync_directory(path)

    monkeypatch.setattr(
        recovery_run_manifest,
        "_sync_recovery_directory",
        fail_final_manifest_directory_sync,
    )
    service = _service(obsidian_service)

    async def scenario() -> None:
        with pytest.raises(OSError, match="final manifest publication failure"):
            await service.start(
                RecoveryPlanRequest(
                    idempotency_key="final-write-failure",
                    expected_plan_hash="0" * 64,
                )
            )

    anyio.run(scenario)

    active_lock = RecoveryActiveLockStore.read()
    assert active_lock is not None
    assert active_lock.run_id == plan.id
    persisted = anyio.run(service.get, plan.id)
    assert persisted is not None
    assert persisted.status is RecoveryRunStatus.COMPLETED
    assert obsidian_service.reindex_calls == 1
    assert manifest_directory_syncs == 2


def test_matching_orphaned_active_record_is_unavailable_and_read_only(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = _plan(key="orphan", automatic=True, steps=())
    RecoveryActiveLockStore.write(plan)
    obsidian_service = _StatusCountingObsidianService()
    service = _service(obsidian_service)
    manifest_path = manifest_path_by_id(plan.id)
    recovery_root = manifest_path.parents[1]
    before_files = _files_under(recovery_root)

    async def scenario() -> None:
        with pytest.raises(RecoveryRunObservationUnavailableError):
            await service.get(plan.id)
        with pytest.raises(RecoveryRunObservationUnavailableError):
            await service.retry(
                plan.id,
                RecoveryPlanRequest(idempotency_key="retry-orphan"),
            )

    anyio.run(scenario)

    assert _files_under(recovery_root) == before_files
    assert RecoveryActiveLockStore.read() is not None
    assert not manifest_path.exists()
    assert obsidian_service.status_reads == 0


def test_plan_hash_drift_fails_apply_fence_closed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Applying a stale plan hash is rejected instead of mutating."""
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="drift",
        automatic=True,
        steps=(RecoveryPlanStep("snapshot_sources", "Snapshot sources", False),),
    )
    plan.plan_hash = "0" * 64

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)

    async def scenario():
        return await _service().start(
            RecoveryPlanRequest(idempotency_key="drift", expected_plan_hash="f" * 64)
        )

    run = anyio.run(scenario)
    assert run.status is RecoveryRunStatus.BLOCKED
    assert run.error_code == "RECOVERY_PLAN_DRIFT"
    assert run.step_results == ()


def test_plan_hash_match_proceeds_with_apply(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The matching plan hash admits the planned mutations."""
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="fenced",
        automatic=True,
        steps=(RecoveryPlanStep("snapshot_sources", "Snapshot sources", False),),
    )
    plan.plan_hash = "0" * 64

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)

    async def scenario():
        return await _service().start(
            RecoveryPlanRequest(idempotency_key="fenced", expected_plan_hash="0" * 64)
        )

    run = anyio.run(scenario)
    assert run.status is RecoveryRunStatus.COMPLETED


@pytest.mark.parametrize("expected_hash", ["0" * 64, "f" * 64])
def test_retry_preserves_apply_fence_and_parent_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expected_hash: str
) -> None:
    """A retry admits only the reviewed plan and retains its parent identity."""
    monkeypatch.chdir(tmp_path)
    obsidian_service = _CountingCompileObsidianService()
    service = _service(obsidian_service)

    async def fake_plan(self, request: RecoveryPlanRequest) -> RecoveryPlan:
        del self
        plan = _plan(
            key=request.idempotency_key or "generated",
            automatic=request.parent_run_id is not None,
            steps=(RecoveryPlanStep("VAULT_REINDEX", "Rebuild vault", True),),
        )
        plan.parent_run_id = request.parent_run_id
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)

    async def scenario() -> tuple[RecoveryRun, RecoveryRun | None]:
        parent = await service.start(RecoveryPlanRequest(idempotency_key="parent"))
        child = await service.retry(
            parent.id,
            RecoveryPlanRequest(
                idempotency_key="child", expected_plan_hash=expected_hash
            ),
        )
        return parent, child

    parent, child = anyio.run(scenario)
    assert parent.status is RecoveryRunStatus.BLOCKED
    assert child is not None
    assert child.parent_run_id == parent.id
    if expected_hash == "0" * 64:
        assert child.status is RecoveryRunStatus.COMPLETED
        assert obsidian_service.reindex_calls == 1
    else:
        assert child.status is RecoveryRunStatus.BLOCKED
        assert child.error_code == "RECOVERY_PLAN_DRIFT"
        assert obsidian_service.reindex_calls == 0


def test_vault_compile_evidence_is_required_by_current_readiness_check(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful vault compile results fence the post-compile readiness read."""
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="compile-fence",
        automatic=True,
        steps=(
            RecoveryPlanStep("VAULT_REINDEX", "Rebuild vault", True),
            RecoveryPlanStep("CURRENT_READINESS_CHECK", "Check readiness", False),
        ),
    )
    plan.plan_hash = "0" * 64

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)
    service = _service(_FakeCompileObsidianService())
    captured: dict[str, object] = {}

    async def verify(plan, **kwargs):
        del plan
        captured.update(kwargs)
        return {"ready": True}

    monkeypatch.setattr(service._verification, "verify_readiness", verify)

    async def scenario():
        return await service.start(
            RecoveryPlanRequest(
                idempotency_key="compile-fence", expected_plan_hash="0" * 64
            )
        )

    run = anyio.run(scenario)

    assert run.status is RecoveryRunStatus.COMPLETED
    assert captured == {
        "compile_receipt_required": True,
        "expected_compile_policy_version": "policy-current",
        "expected_compile_plan_fingerprint": "a" * 64,
    }


def test_failed_note_repair_fails_run_before_embedding_lane(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One unparseable error note fails the run before any embedding rebuild."""
    monkeypatch.chdir(tmp_path)
    obsidian = _FakeRepairObsidianService(failing_paths={"Alexandria/Broken.md"})
    plan = _plan(
        key="note-repair",
        automatic=True,
        steps=(
            RecoveryPlanStep("snapshot_sources", "Snapshot sources", False),
            RecoveryPlanStep(
                "repair_error_notes",
                "Re-parse and revalidate index-error notes in place",
                True,
            ),
            RecoveryPlanStep(
                "reindex_embeddings", "Rebuild retrieval embeddings", True
            ),
        ),
    )
    plan.error_note_repairs = ("Alexandria/Ok.md", "Alexandria/Broken.md")

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)

    async def scenario():
        return await _service(obsidian).start(
            RecoveryPlanRequest(
                idempotency_key="note-repair", expected_plan_hash="0" * 64
            )
        )

    run = anyio.run(scenario)
    assert run.status is RecoveryRunStatus.FAILED
    assert run.error_code == "NOTE_REPAIR_REQUIRED"
    assert "reindex_embeddings" not in [step.code for step in run.step_results], (
        "embedding lane must not run after a failed note repair"
    )
    repair_result = next(
        step.result for step in run.step_results if step.code == "repair_error_notes"
    )
    assert repair_result["requires_manual_repair"] == [
        {
            "path": "Alexandria/Broken.md",
            "error": "unparseable source: Alexandria/Broken.md",
        }
    ]
    assert repair_result["repaired"] == [
        {
            "path": "Alexandria/Ok.md",
            "note_id": "note-Alexandria/Ok.md",
            "content_hash": "a" * 64,
        }
    ]


def test_successful_note_repair_records_each_note_truthfully(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All repaired notes stay recorded when the whole lane succeeds."""
    monkeypatch.chdir(tmp_path)
    obsidian = _FakeRepairObsidianService(failing_paths=set())
    plan = _plan(
        key="note-repair-ok",
        automatic=True,
        steps=(
            RecoveryPlanStep("snapshot_sources", "Snapshot sources", False),
            RecoveryPlanStep(
                "repair_error_notes",
                "Re-parse and revalidate index-error notes in place",
                True,
            ),
        ),
    )
    plan.error_note_repairs = ("Alexandria/A.md", "Alexandria/B.md")

    async def fake_plan(self, request):
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)

    async def scenario():
        return await _service(obsidian).start(
            RecoveryPlanRequest(
                idempotency_key="note-repair-ok", expected_plan_hash="0" * 64
            )
        )

    run = anyio.run(scenario)
    assert run.status is RecoveryRunStatus.COMPLETED
    repair_step = next(
        step for step in run.step_results if step.code == "repair_error_notes"
    )
    assert len(repair_step.result["repaired"]) == 2
    assert repair_step.result["requires_manual_repair"] == []


def test_admit_rolls_back_manifest_on_lock_write_failure_and_rejects_corrupt_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed active-lock writes unlink the manifest; corrupt manifests raise ObservationUnavailable."""
    monkeypatch.chdir(tmp_path)
    plan = _plan(
        key="lock-rollback",
        automatic=True,
        steps=(RecoveryPlanStep("snapshot_sources", "Snapshot sources", False),),
    )

    async def fake_plan(self, request: RecoveryPlanRequest) -> RecoveryPlan:
        del self, request
        return plan

    monkeypatch.setattr(RecoveryPlanService, "plan", fake_plan)
    original_write_record = RecoveryActiveLockStore.write_record

    def fail_lock_write(
        plan: RecoveryPlan, *, started_at: datetime | None = None
    ) -> None:
        del plan, started_at
        raise OSError("simulated active lock write failure")

    monkeypatch.setattr(RecoveryActiveLockStore, "write_record", fail_lock_write)
    service = _service()

    async def fail_scenario() -> None:
        with pytest.raises(OSError, match="simulated active lock write failure"):
            await service.start(
                RecoveryPlanRequest(
                    idempotency_key="lock-rollback", expected_plan_hash="0" * 64
                )
            )

    anyio.run(fail_scenario)
    manifest_file = manifest_path_by_id(plan.id)
    assert not manifest_file.exists()
    assert not active_lock_path().exists()
    assert RecoveryActiveLockStore.read() is None

    monkeypatch.setattr(RecoveryActiveLockStore, "write_record", original_write_record)
    sync_directory = recovery_run_manifest._sync_recovery_directory

    def fail_lock_directory_sync(path: Path) -> None:
        if path == active_lock_path().parent:
            raise OSError("simulated active lock directory sync failure")
        sync_directory(path)

    monkeypatch.setattr(
        recovery_run_manifest,
        "_sync_recovery_directory",
        fail_lock_directory_sync,
    )

    async def fail_lock_sync_scenario() -> None:
        with pytest.raises(
            OSError, match="simulated active lock directory sync failure"
        ):
            await service.start(
                RecoveryPlanRequest(
                    idempotency_key="lock-rollback", expected_plan_hash="0" * 64
                )
            )

    anyio.run(fail_lock_sync_scenario)
    assert not manifest_file.exists()
    assert not active_lock_path().exists()
    assert RecoveryActiveLockStore.read() is None

    monkeypatch.setattr(
        recovery_run_manifest,
        "_sync_recovery_directory",
        sync_directory,
    )
    monkeypatch.setattr(RecoveryActiveLockStore, "write_record", fail_lock_write)
    original_unlink = Path.unlink

    def fail_active_lock_unlink(self: Path, missing_ok: bool = False) -> None:
        if self == active_lock_path():
            raise OSError("simulated active lock unlink failure")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_active_lock_unlink)

    async def fail_lock_unlink_scenario() -> None:
        with pytest.raises(OSError, match="simulated active lock unlink failure"):
            await service.start(
                RecoveryPlanRequest(
                    idempotency_key="lock-rollback", expected_plan_hash="0" * 64
                )
            )

    anyio.run(fail_lock_unlink_scenario)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    monkeypatch.setattr(RecoveryActiveLockStore, "write_record", original_write_record)
    assert not manifest_file.exists()

    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text("{corrupt-json", encoding="utf-8")

    async def corrupt_scenario() -> None:
        with pytest.raises(RecoveryRunObservationUnavailableError):
            await service.start(
                RecoveryPlanRequest(
                    idempotency_key="lock-rollback", expected_plan_hash="0" * 64
                )
            )

    anyio.run(corrupt_scenario)
