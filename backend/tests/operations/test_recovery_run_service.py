"""PostgreSQL-native recovery run lifecycle tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService

from app.operations.application.recovery.execution.recovery_run_errors import (
    RecoveryInProgressError,
)
from app.operations.application.recovery.execution.recovery_run_manifest import (
    _write_active_lock,
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
    _write_active_lock(plan)

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
