"""Compile evidence absence and provenance are explicit readiness contracts."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import anyio
import pytest
from tests.obsidian.test_obsidian_frontmatter_repair import _services
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService
from tests.operations.test_operational_readiness_service import (
    _FakeContextService,
    _FakeObsidianService,
    _healthy_rag,
    _HealthyPostgresDatabase,
    _obsidian_status,
)

from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.operations.application.readiness.operational_compile_receipt_policy import (
    compile_receipt_snapshot,
)
from app.operations.application.readiness.operational_readiness_policy import _blockers
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.interface.schemas.operations.operational_readiness_schema import (
    OperationalCompileReceiptSnapshotResponse,
)
from app.shared.infrastructure.database import Database


@pytest.mark.parametrize(
    ("required", "present", "expected_policy", "status", "blocked"),
    [
        (False, False, None, "NOT_APPLICABLE", False),
        (True, False, None, "REQUIRED_MISSING", True),
        (True, True, "policy-current", "REQUIRED_AND_PRESENT", False),
        (False, True, None, "OPTIONAL_PRESENT", False),
        (True, True, "policy-new", "STALE", True),
    ],
)
def test_compile_receipt_classification_and_blocker_consistency(
    required: bool,
    present: bool,
    expected_policy: str | None,
    status: str,
    blocked: bool,
) -> None:
    """Missing optional evidence is quiet; missing or stale required evidence blocks."""
    raw = (
        {
            "applied_at": datetime(2026, 9, 30, tzinfo=UTC).isoformat(),
            "plan_fingerprint": "a" * 64,
            "policy_version": "policy-current",
            "changed_documents": 1,
            "removed_documents": 0,
            "embedding_invalidated_documents": 1,
            "diagnostic_count": 0,
        }
        if present
        else None
    )
    snapshot = compile_receipt_snapshot(
        raw, required=required, expected_policy_version=expected_policy
    )
    response = OperationalCompileReceiptSnapshotResponse.from_entity(
        snapshot
    ).model_dump(mode="json")
    assert response["status"] == status
    assert response["required"] == required
    assert response["available"] == present
    assert bool(_blockers(list(snapshot.blockers))) == blocked
    if status == "NOT_APPLICABLE":
        assert snapshot.warnings == snapshot.blockers == ()


def test_corrupt_receipt_is_invalid_instead_of_optional_absence() -> None:
    """Malformed persisted evidence cannot masquerade as a healthy optional path."""
    snapshot = compile_receipt_snapshot({"applied_at": "2026-09-30T00:00:00"})
    assert snapshot.status == "INVALID"
    assert snapshot.available is True
    assert snapshot.blockers == ("compile_receipt_invalid",)


def test_compile_receipt_plan_fingerprint_drift_is_stale() -> None:
    """A required path rejects a receipt from a different applied source plan."""
    receipt = {
        "applied_at": datetime(2026, 9, 30, tzinfo=UTC).isoformat(),
        "plan_fingerprint": "a" * 64,
        "policy_version": "policy-current",
        "changed_documents": 1,
        "removed_documents": 0,
        "embedding_invalidated_documents": 0,
        "diagnostic_count": 0,
    }

    snapshot = compile_receipt_snapshot(
        receipt,
        required=True,
        expected_policy_version="policy-current",
        expected_plan_fingerprint="b" * 64,
    )

    assert snapshot.status == "STALE"
    assert snapshot.blockers == ("compile_receipt_stale",)


def test_required_missing_receipt_never_reports_ready(tmp_path: Path) -> None:
    """The composed readiness result propagates required evidence failures."""

    async def scenario():
        service = OperationalReadinessService(
            database=cast(Database, _HealthyPostgresDatabase()),
            context_service=_FakeContextService(_healthy_rag()),
            obsidian_service=_FakeObsidianService(_obsidian_status(tmp_path)),
            graph_projection_service=HealthyGraphProjectionService(),
            compile_receipt_required=True,
        )
        return await service.snapshot()

    snapshot = anyio.run(scenario)
    assert snapshot.ready is False
    assert snapshot.compile_receipt.status == "REQUIRED_MISSING"
    assert "compile_receipt_required" in snapshot.blockers


def test_required_readiness_rejects_stale_compile_plan_fingerprint(
    tmp_path: Path,
) -> None:
    """The composed readiness owner blocks a stale native compile receipt."""

    class _StaleReceiptObsidian(_FakeObsidianService):
        async def latest_compile_receipt(self):
            return {
                "applied_at": datetime(2026, 9, 30, tzinfo=UTC).isoformat(),
                "plan_fingerprint": "a" * 64,
                "policy_version": "policy-current",
                "changed_documents": 1,
                "removed_documents": 0,
                "embedding_invalidated_documents": 0,
                "diagnostic_count": 0,
            }

    async def scenario():
        service = OperationalReadinessService(
            database=cast(Database, _HealthyPostgresDatabase()),
            context_service=_FakeContextService(_healthy_rag()),
            obsidian_service=_StaleReceiptObsidian(_obsidian_status(tmp_path)),
            graph_projection_service=HealthyGraphProjectionService(),
            compile_receipt_required=True,
            expected_compile_policy_version="policy-current",
            expected_compile_plan_fingerprint="b" * 64,
        )
        return await service.snapshot()

    snapshot = anyio.run(scenario)

    assert snapshot.ready is False
    assert snapshot.compile_receipt.status == "STALE"
    assert "compile_receipt_stale" in snapshot.blockers


def test_receipt_reader_uses_the_canonical_compiler_run_store(tmp_path: Path) -> None:
    """Real persisted compile evidence is surfaced instead of perpetual absence."""

    async def scenario():
        database, session, service = await _services(tmp_path)
        try:
            assert await service.latest_compile_receipt() is None
            receipt = {"plan_fingerprint": "a" * 64, "policy_version": "policy-current"}
            ObsidianReportBundleRunStore(vault_path=tmp_path / "vault").save(
                "compile-receipt:latest", receipt
            )
            assert await service.latest_compile_receipt() == receipt
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)
