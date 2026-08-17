"""HTTP contract test for reconciliation-aware temporal memory recall."""

from __future__ import annotations

from datetime import UTC, datetime

from app.main import app
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryTemporalRecallMatch,
    MemoryTemporalRecallPack,
    MemoryTemporalState,
)
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    RagStrategy,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from fastapi.testclient import TestClient
from tests.shared.provider_overrides import override_library_provider

NOW = datetime(2026, 7, 25, tzinfo=UTC)


class FakeTemporalRecallService:
    """Capture converted temporal recall requests and return one enriched match."""

    def __init__(self, pack: MemoryTemporalRecallPack) -> None:
        self.pack = pack
        self.requests: list[MemoryTemporalRecallRequest] = []

    async def recall(
        self,
        request: MemoryTemporalRecallRequest,
    ) -> MemoryTemporalRecallPack:
        self.requests.append(request)
        return self.pack


def _pack() -> MemoryTemporalRecallPack:
    context = ContextRecord(
        id="obsidian:current",
        kind=ContextKind.MEMORY,
        title="Current memory",
        summary="Current storage decision",
        content="heterarchy-alexandria uses PostgreSQL.",
        content_format=ContextContentFormat.MARKDOWN,
        project="heterarchy-alexandria",
        scope=ContextScope.PROJECT,
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="Hermes",
        source_type=ContextSourceType.AGENT,
        importance=ContextImportance.HIGH,
        tags=["memory"],
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=[],
        restore_prompt=None,
        context_metadata={},
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )
    match = ContextSearchMatch(
        context=context,
        chunk=ContextChunkRecord(
            id="chunk-current",
            context_id=context.id,
            chunk_index=0,
            heading="Decision",
            content=context.content,
            token_count=5,
            content_hash="chunk-hash",
            chunk_metadata={},
            created_at=NOW,
        ),
        score=1.0,
        fts_score=1.0,
        vector_score=1.0,
        why_retrieved="current temporal match",
    )
    state = MemoryTemporalState(
        context_id=context.id,
        recorded_at=NOW,
        observed_at=NOW,
        valid_from=NOW,
        valid_to=None,
        is_current=True,
        conflict_set_ids=("conflict-1",),
        supersedes=("obsidian:old",),
        relation_summary=("supersedes:obsidian:old",),
    )
    return MemoryTemporalRecallPack(
        query="storage decision",
        mode=MemoryTemporalRecallMode.CURRENT,
        as_of=None,
        strategy=RagStrategy.HYBRID,
        effective_strategy=RagStrategy.HYBRID,
        warnings=("Temporal recall includes conflict-1",),
        recall_scopes=(ContextScope.PROJECT,),
        matches=(
            MemoryTemporalRecallMatch(
                match=match,
                temporal_state=state,
                is_current=True,
                conflict_set_ids=state.conflict_set_ids,
                supersedes=state.supersedes,
                relation_summary=state.relation_summary,
            ),
        ),
        context_pack="Current memory pack",
    )


def test_temporal_recall_http_contract_preserves_reconciliation_metadata() -> None:
    service = FakeTemporalRecallService(_pack())
    with (
        override_library_provider("memory_temporal_recall_service", service),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/memory/reconciliation/recall",
            json={
                "query": " storage decision ",
                "mode": "CURRENT",
                "strategy": "HYBRID",
                "limit": 5,
                "project": "heterarchy-alexandria",
                "include_scopes": ["PROJECT"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "CURRENT"
    assert payload["matches"][0]["is_current"] is True
    assert payload["matches"][0]["conflict_set_ids"] == ["conflict-1"]
    assert payload["matches"][0]["supersedes"] == ["obsidian:old"]
    valid_from = payload["matches"][0]["temporal_state"]["valid_from"]
    assert datetime.fromisoformat(valid_from.replace("Z", "+00:00")) == NOW
    assert service.requests[0].query == "storage decision"
    assert service.requests[0].mode is MemoryTemporalRecallMode.CURRENT
    assert service.requests[0].include_scopes == (ContextScope.PROJECT,)
