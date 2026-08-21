"""HTTP contract tests for memory reconciliation endpoints."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from app.main import app
from app.memory.application.reconciliation.candidates.memory_candidate_service import (
    MemoryCandidateService,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_plan_service import (
    MemoryReconciliationPlanService,
)
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryCandidateCreate,
    MemoryReconciliationPreviewRequest,
)
from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    MemoryConflictSet,
    MemoryReconciliationPlan,
    MemoryReconciliationResult,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryConflictStatus,
    MemoryReconciliationStatus,
)
from fastapi.testclient import TestClient
from tests.shared.provider_overrides import override_library_provider

NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _candidate_contract() -> MemoryCandidateCreate:
    return MemoryCandidateCreate(
        candidate_id="candidate-api",
        title="API memory decision",
        body="heterarchy-alexandria uses PostgreSQL.",
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        canonical_claims=(
            CanonicalClaim(
                subject="heterarchy-alexandria",
                predicate="uses",
                object="PostgreSQL",
                scope=ContextScope.PROJECT,
                project="heterarchy-alexandria",
                valid_from=NOW,
            ),
        ),
        tags=("memory",),
        recorded_at=NOW,
        observed_at=NOW,
        valid_from=NOW,
    )


def _plan() -> MemoryReconciliationPlan:
    candidate = MemoryCandidateService().create(_candidate_contract())
    return MemoryReconciliationPlanService().build(
        candidate=candidate,
        decisions=(),
        idempotency_key="api-preview-1",
    )


def _result(plan: MemoryReconciliationPlan) -> MemoryReconciliationResult:
    return MemoryReconciliationResult(
        reconciliation_id="result-api",
        plan_id=plan.plan_id,
        status=MemoryReconciliationStatus.APPLIED,
        created_context_ids=("obsidian:candidate-api",),
        hard_delete_performed=False,
        completed_at=NOW,
    )


def _conflict() -> MemoryConflictSet:
    return MemoryConflictSet(
        conflict_set_id="conflict-api",
        context_ids=("obsidian:candidate-api", "obsidian:context-old"),
        candidate_id="candidate-api",
        subject_key="heterarchy-alexandria",
        claim_key="heterarchy-alexandria|uses|PostgreSQL",
        scope=ContextScope.PROJECT,
        validity_overlap=True,
        reason="Conflicting active storage decisions",
        status=MemoryConflictStatus.OPEN,
        resolution=None,
        created_at=NOW,
        resolved_at=None,
    )


class FakePreviewService:
    """Return one stable plan and capture the converted application request."""

    def __init__(self, plan: MemoryReconciliationPlan) -> None:
        self.plan = plan
        self.requests: list[MemoryReconciliationPreviewRequest] = []

    async def preview(
        self,
        request: MemoryReconciliationPreviewRequest,
    ) -> MemoryReconciliationPlan:
        self.requests.append(request)
        return self.plan


class FakeApplyService:
    """Return one stable result and capture retry semantics."""

    def __init__(self, result: MemoryReconciliationResult) -> None:
        self.result = result
        self.calls: list[tuple[str, bool]] = []

    async def apply(
        self,
        plan_id: str,
        *,
        retry_failed: bool = False,
    ) -> MemoryReconciliationResult:
        self.calls.append((plan_id, retry_failed))
        return self.result


class FakeQueryService:
    """Expose one plan and result through read-only route use cases."""

    def __init__(
        self,
        plan: MemoryReconciliationPlan,
        result: MemoryReconciliationResult,
    ) -> None:
        self.plan = plan
        self.result = result

    async def get_plan(self, plan_id: str) -> MemoryReconciliationPlan:
        assert plan_id == self.plan.plan_id
        return self.plan

    async def get_result(
        self,
        reconciliation_id: str,
    ) -> MemoryReconciliationResult:
        assert reconciliation_id == self.result.reconciliation_id
        return self.result

    async def list_review_plans(
        self,
        *,
        limit: int = 100,
    ) -> list[MemoryReconciliationPlan]:
        assert limit == 25
        return [
            replace(
                self.plan,
                requires_review=True,
                status=MemoryReconciliationStatus.REVIEW_REQUIRED,
            )
        ]


class FakeConflictService:
    """Provide mutable explicit conflict review and resolution behavior."""

    def __init__(self, conflict: MemoryConflictSet) -> None:
        self.conflict = conflict
        self.list_calls: list[tuple[MemoryConflictStatus | None, int]] = []

    async def list(
        self,
        *,
        status: MemoryConflictStatus | None = None,
        limit: int = 100,
    ) -> list[MemoryConflictSet]:
        self.list_calls.append((status, limit))
        if status is not None and self.conflict.status is not status:
            return []
        return [self.conflict]

    async def get(self, conflict_set_id: str) -> MemoryConflictSet:
        assert conflict_set_id == self.conflict.conflict_set_id
        return self.conflict

    async def mark_reviewing(self, conflict_set_id: str) -> MemoryConflictSet:
        assert conflict_set_id == self.conflict.conflict_set_id
        self.conflict = replace(
            self.conflict,
            status=MemoryConflictStatus.REVIEWING,
        )
        return self.conflict

    async def resolve(
        self,
        conflict_set_id: str,
        *,
        status: MemoryConflictStatus,
        resolution: str,
    ) -> MemoryConflictSet:
        assert conflict_set_id == self.conflict.conflict_set_id
        self.conflict = replace(
            self.conflict,
            status=status,
            resolution=resolution,
            resolved_at=NOW,
        )
        return self.conflict


def _preview_payload() -> dict[str, object]:
    return {
        "candidate": {
            "candidate_id": "candidate-api",
            "title": " API memory decision ",
            "body": "heterarchy-alexandria uses PostgreSQL.",
            "scope": "PROJECT",
            "project": "heterarchy-alexandria",
            "canonical_claims": [
                {
                    "subject": "heterarchy-alexandria",
                    "predicate": "uses",
                    "object": "PostgreSQL",
                    "valid_from": NOW.isoformat(),
                    "polarity": "POSITIVE",
                }
            ],
            "tags": ["memory", "memory"],
            "recorded_at": NOW.isoformat(),
            "observed_at": NOW.isoformat(),
            "valid_from": NOW.isoformat(),
        },
        "idempotency_key": "api-preview-1",
        "recall_limit": 20,
    }


def test_reconciliation_http_preview_apply_and_query_contracts() -> None:
    plan = _plan()
    result = _result(plan)
    preview_service = FakePreviewService(plan)
    apply_service = FakeApplyService(result)
    query_service = FakeQueryService(plan, result)
    with (
        override_library_provider("reconciliation_preview_service", preview_service),
        override_library_provider("reconciliation_apply_service", apply_service),
        override_library_provider("reconciliation_query_service", query_service),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        preview_response = client.post(
            "/memory/reconciliation/preview",
            json=_preview_payload(),
        )
        plan_response = client.get(f"/memory/reconciliation/plans/{plan.plan_id}")
        review_queue_response = client.get(
            "/memory/reconciliation/review-queue",
            params={"limit": 25},
        )
        apply_response = client.post(
            f"/memory/reconciliation/plans/{plan.plan_id}/apply",
            json={"retry_failed": True},
        )
        result_response = client.get(
            f"/memory/reconciliation/results/{result.reconciliation_id}"
        )

    assert preview_response.status_code == 200
    assert preview_response.json()["plan_id"] == plan.plan_id
    assert preview_response.json()["primary_decision"] == "UNRELATED"
    assert preview_service.requests[0].candidate.scope is ContextScope.PROJECT
    assert preview_service.requests[0].candidate.tags == ("memory",)
    assert plan_response.status_code == 200
    assert review_queue_response.status_code == 200
    assert review_queue_response.json()["total"] == 1
    assert review_queue_response.json()["items"][0]["requires_review"] is True
    assert apply_response.status_code == 200
    assert apply_response.json()["hard_delete_performed"] is False
    assert apply_service.calls == [(plan.plan_id, True)]
    assert result_response.status_code == 200
    assert result_response.json()["reconciliation_id"] == "result-api"


def test_reconciliation_http_conflict_review_and_resolution_contracts() -> None:
    conflict_service = FakeConflictService(_conflict())
    with (
        override_library_provider("memory_conflict_service", conflict_service),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        list_response = client.get(
            "/memory/reconciliation/conflicts",
            params={"status": "OPEN", "limit": 10},
        )
        get_response = client.get("/memory/reconciliation/conflicts/conflict-api")
        reviewing_response = client.post(
            "/memory/reconciliation/conflicts/conflict-api/reviewing"
        )
        resolve_response = client.post(
            "/memory/reconciliation/conflicts/conflict-api/resolve",
            json={
                "status": "RESOLVED_KEEP_BOTH",
                "resolution": "Both claims apply to different operational contexts.",
            },
        )

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert conflict_service.list_calls == [(MemoryConflictStatus.OPEN, 10)]
    assert get_response.status_code == 200
    assert reviewing_response.status_code == 200
    assert reviewing_response.json()["status"] == "REVIEWING"
    assert resolve_response.status_code == 200
    assert resolve_response.json()["status"] == "RESOLVED_KEEP_BOTH"
    assert resolve_response.json()["resolution"].startswith("Both claims")


def test_reconciliation_http_rejects_naive_time_and_invalid_resolution() -> None:
    conflict_service = FakeConflictService(_conflict())
    payload = _preview_payload()
    candidate = payload["candidate"]
    assert isinstance(candidate, dict)
    candidate["recorded_at"] = "2026-07-25T00:00:00"
    with (
        override_library_provider("memory_conflict_service", conflict_service),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        preview_response = client.post(
            "/memory/reconciliation/preview",
            json=payload,
        )
        resolution_response = client.post(
            "/memory/reconciliation/conflicts/conflict-api/resolve",
            json={"status": "OPEN", "resolution": "not final"},
        )

    assert preview_response.status_code == 422
    assert resolution_response.status_code == 422
