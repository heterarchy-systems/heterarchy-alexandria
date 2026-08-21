"""Service and HTTP tests for reconciliation-aware Memory Compact preview."""

from __future__ import annotations

from app.main import app
from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_policy import (
    MemoryCompactReconciliationPolicy,
)
from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_service import (
    MemoryCompactReconciliationService,
)
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCompactFactBuckets,
    MemoryCompactSafetyReview,
    MemoryTemporalRecallPack,
)
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from fastapi.testclient import TestClient
from tests.shared.provider_overrides import override_library_provider


class RecordingTemporalRecallService:
    """Capture the effective temporal mode selected for Compact preparation."""

    def __init__(self) -> None:
        self.requests: list[MemoryTemporalRecallRequest] = []

    async def recall(
        self,
        request: MemoryTemporalRecallRequest,
    ) -> MemoryTemporalRecallPack:
        self.requests.append(request)
        return MemoryTemporalRecallPack(
            query=request.query,
            mode=request.mode,
            as_of=request.as_of,
            strategy=request.strategy,
            effective_strategy=request.strategy,
            warnings=(),
            recall_scopes=(ContextScope.PROJECT,),
            matches=(),
            context_pack="",
        )


class FakeCompactPreviewService:
    """Return one stable Compact safety review for the HTTP boundary."""

    def __init__(self, review: MemoryCompactSafetyReview) -> None:
        self.review = review
        self.requests: list[MemoryTemporalRecallRequest] = []

    async def prepare(
        self,
        request: MemoryTemporalRecallRequest,
    ) -> MemoryCompactSafetyReview:
        self.requests.append(request)
        return self.review


def test_compact_service_forces_all_temporal_states_before_classification() -> None:
    temporal = RecordingTemporalRecallService()
    service = MemoryCompactReconciliationService(
        temporal_recall_service=temporal,
        policy=MemoryCompactReconciliationPolicy(),
    )

    import anyio

    review = anyio.run(
        service.prepare,
        MemoryTemporalRecallRequest(
            query="storage decision",
            mode=MemoryTemporalRecallMode.CURRENT,
            strategy=RagStrategy.HYBRID,
            limit=20,
            project="heterarchy-alexandria",
            include_scopes=(ContextScope.PROJECT,),
        ),
    )

    assert temporal.requests[0].mode is MemoryTemporalRecallMode.ALL
    assert temporal.requests[0].project == "heterarchy-alexandria"
    assert review.safe_to_publish is True
    assert review.rendered_markdown.startswith("## Current Facts")


def test_compact_preview_http_contract_returns_all_fact_sections() -> None:
    review = MemoryCompactSafetyReview(
        buckets=MemoryCompactFactBuckets(),
        issues=(),
        safe_to_publish=True,
        warnings=("No matching facts were recalled.",),
        rendered_markdown=(
            "## Current Facts\n- None\n\n"
            "## Historical Facts\n- None\n\n"
            "## Open Conflicts\n- None\n\n"
            "## Uncertain Claims\n- None\n\n"
            "## Superseded Facts\n- None\n"
        ),
    )
    service = FakeCompactPreviewService(review)
    with (
        override_library_provider(
            "memory_compact_reconciliation_service",
            service,
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/memory/reconciliation/compact/preview",
            json={
                "query": " storage decision ",
                "mode": "CURRENT",
                "strategy": "HYBRID",
                "limit": 10,
                "project": "heterarchy-alexandria",
                "include_scopes": ["PROJECT"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["safe_to_publish"] is True
    assert payload["issues"] == []
    assert payload["buckets"] == {
        "current_facts": [],
        "historical_facts": [],
        "open_conflicts": [],
        "uncertain_claims": [],
        "superseded_facts": [],
    }
    assert "## Open Conflicts" in payload["rendered_markdown"]
    assert service.requests[0].query == "storage decision"
    assert service.requests[0].mode is MemoryTemporalRecallMode.CURRENT
