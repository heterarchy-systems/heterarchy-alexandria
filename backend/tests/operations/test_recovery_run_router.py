"""PostgreSQL-native recovery router contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from fastapi import HTTPException, Request
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService
from tests.operations.test_recovery_run_service import _plan

from app.operations.application.recovery.execution.recovery_run_manifest import (
    RecoveryActiveLockStore,
    RecoveryManifestStore,
    active_lock_path,
    manifest_path_by_id,
)
from app.operations.application.recovery.execution.recovery_run_service import (
    RecoveryRunService,
)
from app.operations.domain.entities.recovery_plan import RecoverySourceSnapshot
from app.operations.domain.entities.recovery_run import RecoveryRun
from app.operations.domain.event_enum.operational_recovery_enums import (
    RecoveryRunStatus,
)
from app.operations.interface.routers.recovery_run_router import (
    get_recovery_run,
    recovery_run,
    retry_recovery_run,
)
from app.operations.interface.schemas.operations.recovery_run_schema import (
    RecoveryRunRequestSchema,
    RecoveryRunRetryRequestSchema,
)


def _files_under(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/operations/recovery/runs",
            "headers": [],
            "query_string": b"",
        }
    )


def _run(*, run_id: str = "run-1", parent_run_id: str | None = None) -> RecoveryRun:
    now = datetime.now(UTC)
    return RecoveryRun(
        id=run_id,
        parent_run_id=parent_run_id,
        idempotency_key=f"key-{run_id}",
        trigger="manual",
        actor="test",
        status=RecoveryRunStatus.COMPLETED,
        current_step="snapshot_sources",
        started_at=now,
        updated_at=now,
        finished_at=now,
        source_snapshot=RecoverySourceSnapshot(
            vault_path="/vault",
            alexandria_root="Alexandria",
            managed_markdown_count=1,
            representative_path="/vault/Alexandria/note.md",
            representative_sha256="abc",
            disk_free_bytes=1_000_000,
            markdown_manifest={"Alexandria/note.md": "1:1"},
        ),
        diagnosis=(),
        planned_steps=(),
        step_results=(),
        rebuild_results={},
        verification_results={"ready": True},
        error_code=None,
        error_summary=None,
        next_actions=(),
        manifest_path=f"/tmp/{run_id}/recovery-run.json",
    )


def test_recovery_run_route_returns_current_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _run()

    async def fake_start(self, request):
        del self, request
        return expected

    monkeypatch.setattr(RecoveryRunService, "start", fake_start)

    async def scenario():
        return await recovery_run(
            request=RecoveryRunRequestSchema(
                idempotency_key="key-run-1", expected_plan_hash="0" * 64
            ),
            http_request=_request(),
            database=SimpleNamespace(),
            context_service=SimpleNamespace(),
            obsidian_service=SimpleNamespace(),
            graph_projection_service=HealthyGraphProjectionService(),
            context_service_factory=lambda: SimpleNamespace(),
            obsidian_service_factory=lambda: SimpleNamespace(),
            callbacks=None,
        )

    response = anyio.run(scenario)
    payload = response.model_dump(mode="json")
    assert payload["id"] == "run-1"
    assert payload["status"] == "COMPLETED"
    assert "quarantine_artifacts" not in payload


def test_get_unknown_recovery_run_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(self, run_id):
        del self, run_id
        return None

    monkeypatch.setattr(RecoveryRunService, "get", fake_get)

    async def scenario():
        with pytest.raises(HTTPException) as raised:
            await get_recovery_run(
                run_id="missing",
                database=SimpleNamespace(),
                context_service=SimpleNamespace(),
                obsidian_service=SimpleNamespace(),
                graph_projection_service=HealthyGraphProjectionService(),
            )
        return raised.value

    error = anyio.run(scenario)
    assert error.status_code == 404
    assert error.detail == {"code": "RECOVERY_RUN_NOT_FOUND", "run_id": "missing"}


def test_retry_unknown_recovery_run_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_retry(self, run_id, request):
        del self, run_id, request
        return None

    monkeypatch.setattr(RecoveryRunService, "retry", fake_retry)

    async def scenario():
        with pytest.raises(HTTPException) as raised:
            await retry_recovery_run(
                run_id="missing",
                request=RecoveryRunRetryRequestSchema(expected_plan_hash="0" * 64),
                http_request=_request(),
                database=SimpleNamespace(),
                context_service=SimpleNamespace(),
                obsidian_service=SimpleNamespace(),
                graph_projection_service=HealthyGraphProjectionService(),
                context_service_factory=lambda: SimpleNamespace(),
                obsidian_service_factory=lambda: SimpleNamespace(),
                callbacks=None,
            )
        return raised.value

    error = anyio.run(scenario)
    assert error.status_code == 404
    assert error.detail == {"code": "RECOVERY_RUN_NOT_FOUND", "run_id": "missing"}


def test_orphaned_active_run_get_and_retry_return_stable_503_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = _plan(key="orphan-router", automatic=True, steps=())
    RecoveryActiveLockStore.write(plan)
    active_path = active_lock_path()
    recovery_root = active_path.parent
    before_files = _files_under(recovery_root)

    async def scenario() -> tuple[HTTPException, HTTPException]:
        with pytest.raises(HTTPException) as raised_get:
            await get_recovery_run(
                run_id=plan.id,
                database=SimpleNamespace(),
                context_service=SimpleNamespace(),
                obsidian_service=SimpleNamespace(),
                graph_projection_service=HealthyGraphProjectionService(),
            )
        with pytest.raises(HTTPException) as raised_retry:
            await retry_recovery_run(
                run_id=plan.id,
                request=RecoveryRunRetryRequestSchema(expected_plan_hash="0" * 64),
                http_request=_request(),
                database=SimpleNamespace(),
                context_service=SimpleNamespace(),
                obsidian_service=SimpleNamespace(),
                graph_projection_service=HealthyGraphProjectionService(),
                context_service_factory=lambda: SimpleNamespace(),
                obsidian_service_factory=lambda: SimpleNamespace(),
                callbacks=None,
            )
        return raised_get.value, raised_retry.value

    get_error, retry_error = anyio.run(scenario)
    expected_detail = {
        "code": "RECOVERY_RUN_OBSERVATION_UNAVAILABLE",
        "run_id": plan.id,
    }
    assert get_error.status_code == 503
    assert get_error.detail == expected_detail
    assert retry_error.status_code == 503
    assert retry_error.detail == expected_detail
    assert _files_under(recovery_root) == before_files
    assert manifest_path_by_id(plan.id).exists() is False


def test_retry_running_parent_returns_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = _plan(key="running-parent", automatic=True, steps=())
    RecoveryActiveLockStore.write(plan)
    manifest_path = manifest_path_by_id(plan.id)
    parent_run = _run(run_id=plan.id)
    parent_run.status = RecoveryRunStatus.RUNNING
    parent_run.finished_at = None
    parent_run.manifest_path = str(manifest_path)
    parent_run.admitted_plan_hash = plan.plan_hash
    RecoveryManifestStore.write(parent_run)

    async def scenario() -> HTTPException:
        with pytest.raises(HTTPException) as raised:
            await retry_recovery_run(
                run_id=plan.id,
                request=RecoveryRunRetryRequestSchema(expected_plan_hash="0" * 64),
                http_request=_request(),
                database=SimpleNamespace(),
                context_service=SimpleNamespace(),
                obsidian_service=SimpleNamespace(),
                graph_projection_service=HealthyGraphProjectionService(),
                context_service_factory=lambda: SimpleNamespace(),
                obsidian_service_factory=lambda: SimpleNamespace(),
                callbacks=None,
            )
        return raised.value

    error = anyio.run(scenario)
    assert error.status_code == 409
    assert error.detail == {
        "code": "RECOVERY_RUN_NOT_RETRYABLE",
        "run_id": plan.id,
        "status": RecoveryRunStatus.RUNNING.value,
    }
