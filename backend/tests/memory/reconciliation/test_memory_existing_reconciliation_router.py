"""HTTP contract tests for existing-memory reconciliation routes."""

from __future__ import annotations

from app.main import app
from app.memory.domain.contracts.memory_existing_reconciliation_contracts import (
    ExistingMemoryReconciliationRequest,
)
from app.memory.domain.entities.memory_existing_reconciliation import (
    ExistingMemoryAssessment,
    ExistingMemoryReconciliationReport,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import MemoryRelationType
from fastapi.testclient import TestClient
from tests.shared.provider_overrides import override_library_provider


class FakeExistingMemoryReconciliationService:
    """Capture preview/apply contracts and return one stable report."""

    def __init__(self) -> None:
        self.preview_requests: list[ExistingMemoryReconciliationRequest] = []
        self.apply_requests: list[ExistingMemoryReconciliationRequest] = []

    async def preview(
        self,
        request: ExistingMemoryReconciliationRequest,
    ) -> ExistingMemoryReconciliationReport:
        self.preview_requests.append(request)
        return _report(dry_run=True, plans_persisted=0)

    async def apply(
        self,
        request: ExistingMemoryReconciliationRequest,
    ) -> ExistingMemoryReconciliationReport:
        self.apply_requests.append(request)
        return _report(dry_run=False, plans_persisted=1)


def _report(
    *,
    dry_run: bool,
    plans_persisted: int,
) -> ExistingMemoryReconciliationReport:
    assessment = ExistingMemoryAssessment(
        context_id="obsidian:context-1",
        temporal_overlay_present=False,
        temporal_backfill_required=True,
        canonical_claim_count=1,
        primary_relation=MemoryRelationType.DUPLICATE,
        related_context_ids=("obsidian:context-2",),
        plan_id="plan-1",
        plan_persisted=plans_persisted == 1,
        requires_review=False,
        warnings=(),
    )
    return ExistingMemoryReconciliationReport(
        dry_run=dry_run,
        scanned=1,
        total_available=1,
        temporal_backfill_candidates=1,
        temporal_states_written=0 if dry_run else 1,
        plans_generated=1,
        plans_persisted=plans_persisted,
        contexts_missing_claims=0,
        review_required=0,
        assessments=(assessment,),
        warnings=(),
        hard_delete_performed=False,
    )


def _payload() -> dict[str, object]:
    return {
        "project": " heterarchy-alexandria ",
        "scope": "PROJECT",
        "include_archived": True,
        "max_contexts": 250,
        "batch_size": 50,
        "recall_limit": 10,
    }


def test_existing_memory_preview_http_contract_is_write_free() -> None:
    service = FakeExistingMemoryReconciliationService()
    with (
        override_library_provider("memory_existing_reconciliation_service", service),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/memory/reconciliation/existing/preview",
            json=_payload(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["temporal_states_written"] == 0
    assert payload["plans_persisted"] == 0
    assert payload["hard_delete_performed"] is False
    assert payload["assessments"][0]["primary_relation"] == "DUPLICATE"
    assert service.preview_requests == [
        ExistingMemoryReconciliationRequest(
            project="heterarchy-alexandria",
            scope=ContextScope.PROJECT,
            include_archived=True,
            max_contexts=250,
            batch_size=50,
            recall_limit=10,
        )
    ]


def test_existing_memory_apply_http_contract_uses_explicit_apply_path() -> None:
    service = FakeExistingMemoryReconciliationService()
    with (
        override_library_provider("memory_existing_reconciliation_service", service),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/memory/reconciliation/existing/apply",
            json=_payload(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["temporal_states_written"] == 1
    assert payload["plans_persisted"] == 1
    assert payload["hard_delete_performed"] is False
    assert service.apply_requests[0].project == "heterarchy-alexandria"
