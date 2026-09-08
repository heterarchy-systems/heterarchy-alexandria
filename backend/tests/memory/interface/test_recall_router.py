"""HTTP boundary evidence for the high-level recall contract."""

from __future__ import annotations

from dependency_injector import providers
from fastapi.testclient import TestClient

from app.main import app
from app.memory.domain.contracts.recall_contracts import RecallRequest
from app.memory.domain.entities.recall import RecallResult, RecallTrace
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.event_enum.recall_enums import RecallOutcome, RecallScopeMode


class _RecallFake:
    """Typed route fake returning one empty, fully shaped recall result."""

    def __init__(self) -> None:
        self.requests: list[RecallRequest] = []

    async def recall(self, request: RecallRequest) -> RecallResult:
        self.requests.append(request)
        return RecallResult(
            query="semantic paraphrase",
            scope_mode=RecallScopeMode.AUTO,
            recall_scopes=(ContextScope.GLOBAL,),
            effective_strategy=RagStrategy.AUTO,
            outcome=RecallOutcome.SEARCH_EXHAUSTED,
            warnings=("PROJECT:identity_unavailable",),
            matches=(),
            context_pack="# Alexandria Context Pack\n",
            trace=RecallTrace(
                stages=(),
                skipped_scopes=("PROJECT:identity_unavailable",),
                fallback_expansion=(),
                degraded_subsystems=(),
                outcome=RecallOutcome.SEARCH_EXHAUSTED,
                confidence=0.0,
                search_call_count=0,
            ),
        )


def test_recall_http_schema_and_auto_scope_trace() -> None:
    """HTTP response publishes bounded outcome and skipped AUTO identity lanes."""
    fake = _RecallFake()
    with (
        app.state.container.recall_service.override(providers.Object(fake)),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/memory/recall",
            json={"query": " semantic paraphrase "},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"] == "SEARCH_EXHAUSTED"
    assert payload["trace"]["skipped_scopes"] == ["PROJECT:identity_unavailable"]
    assert fake.requests[0].query == "semantic paraphrase"
