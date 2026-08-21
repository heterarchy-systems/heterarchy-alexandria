"""PostgreSQL-native recovery run lifecycle tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import anyio
import pytest
from app.operations.application.recovery.planning.recovery_plan_contracts import (
    RecoveryPlanRequest,
)
from app.operations.application.recovery.planning.recovery_plan_service import (
    RecoveryPlanService,
)
from app.operations.application.recovery.execution.recovery_run_errors import (
    RecoveryInProgressError,
)
from app.operations.application.recovery.execution.recovery_run_manifest import (
    _write_active_lock,
)
from app.operations.application.recovery.execution.recovery_run_service import (
    RecoveryRunService,
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


class _FakeObsidianService:
    async def status(self) -> SimpleNamespace:
        return SimpleNamespace(vault_path="/vault", alexandria_root="Alexandria")


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


def _service() -> RecoveryRunService:
    return RecoveryRunService(
        database=SimpleNamespace(),
        context_service=_FakeContextService(),
        obsidian_service=_FakeObsidianService(),
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
        return await _service().start(RecoveryPlanRequest(idempotency_key="blocked"))

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
        first = await service.start(RecoveryPlanRequest(idempotency_key="snapshot"))
        second = await service.start(RecoveryPlanRequest(idempotency_key="snapshot"))
        return first, second

    first, second = anyio.run(scenario)
    assert first.status is RecoveryRunStatus.COMPLETED
    assert [step.code for step in first.step_results] == ["snapshot_sources"]
    assert second == first


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
            RecoveryPlanRequest(idempotency_key="unsupported")
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
            await _service().start(RecoveryPlanRequest(idempotency_key="locked"))
        return raised.value

    error = anyio.run(scenario)
    assert error.run_id == plan.id
    assert error.idempotency_key == plan.idempotency_key
