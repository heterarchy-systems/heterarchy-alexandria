"""MCP contract tests for memory reconciliation tools."""

from __future__ import annotations

import anyio
import httpx
from app.mcp_server.backend_api_client import AlexandriaApiClient, AlexandriaApiSettings
from app.mcp_server.server_runtime import build_mcp_server
from app.mcp_server.tools.memory_reconciliation_tools import (
    alexandria_apply_existing_memory_reconciliation,
    alexandria_apply_memory_reconciliation,
    alexandria_get_memory_conflict,
    alexandria_get_memory_reconciliation_plan,
    alexandria_list_memory_conflicts,
    alexandria_preview_existing_memory_reconciliation,
    alexandria_preview_memory_reconciliation,
    alexandria_preview_reconciliation_memory_compact,
    alexandria_recall_memory_temporally,
    alexandria_resolve_memory_conflict,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryConflictStatus,
    MemoryTemporalRecallMode,
)
from app.memory.interface.schemas.reconciliation.memory_existing_reconciliation_request_schema import (
    ExistingMemoryReconciliationHttpRequest,
)
from app.memory.interface.schemas.reconciliation.memory_reconciliation_candidate_request_schema import (
    MemoryCandidateRequest,
)
from app.memory.interface.schemas.reconciliation.memory_reconciliation_temporal_request_schema import (
    MemoryTemporalRecallHttpRequest,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONValue

RecordedCall = httpx.Request


def _client() -> tuple[AlexandriaApiClient, list[RecordedCall]]:
    calls: list[RecordedCall] = []

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json({"ok": True}))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )
    return client, calls


def _candidate() -> MemoryCandidateRequest:
    return MemoryCandidateRequest(
        title="Storage decision",
        body="heterarchy-alexandria uses Obsidian as canonical storage.",
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        tags=["memory", "canonical"],
        candidate_id="candidate/1",
    )


def _temporal_request() -> MemoryTemporalRecallHttpRequest:
    return MemoryTemporalRecallHttpRequest(
        query="storage decision",
        mode=MemoryTemporalRecallMode.ALL,
        project="heterarchy-alexandria",
        include_scopes=[ContextScope.PROJECT],
    )


def _existing_memory_request() -> ExistingMemoryReconciliationHttpRequest:
    return ExistingMemoryReconciliationHttpRequest(
        project="heterarchy-alexandria",
        scope=ContextScope.PROJECT,
        include_archived=True,
        max_contexts=250,
        batch_size=50,
        recall_limit=10,
    )


def test_memory_reconciliation_gateway_maps_to_backend_contracts() -> None:
    """MCP adapters should preserve safe HTTP paths and request payloads."""
    client, calls = _client()

    async def exercise() -> list[JSONValue]:
        return [
            await alexandria_preview_memory_reconciliation(
                client,
                _candidate(),
                idempotency_key=" preview-key ",
                recall_limit=500,
            ),
            await alexandria_recall_memory_temporally(client, _temporal_request()),
            await alexandria_preview_reconciliation_memory_compact(
                client,
                _temporal_request(),
            ),
            await alexandria_preview_existing_memory_reconciliation(
                client,
                _existing_memory_request(),
            ),
            await alexandria_apply_existing_memory_reconciliation(
                client,
                _existing_memory_request(),
            ),
            await alexandria_get_memory_reconciliation_plan(client, "plan/1"),
            await alexandria_apply_memory_reconciliation(
                client,
                "plan/1",
                retry_failed=True,
            ),
            await alexandria_list_memory_conflicts(
                client,
                status=MemoryConflictStatus.OPEN,
                limit=5000,
            ),
            await alexandria_get_memory_conflict(client, "conflict/1"),
            await alexandria_resolve_memory_conflict(
                client,
                "conflict/1",
                status=MemoryConflictStatus.RESOLVED_KEEP_BOTH,
                resolution="Both claims are valid in different temporal scopes.",
            ),
        ]

    results = anyio.run(exercise)

    assert results == [{"ok": True}] * 10
    assert [call.method for call in calls] == [
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
        "GET",
        "POST",
        "GET",
        "GET",
        "POST",
    ]
    paths = [str(call.url).removeprefix("http://backend:8000") for call in calls]
    assert paths == [
        "/memory/reconciliation/preview",
        "/memory/reconciliation/recall",
        "/memory/reconciliation/compact/preview",
        "/memory/reconciliation/existing/preview",
        "/memory/reconciliation/existing/apply",
        "/memory/reconciliation/plans/plan%2F1",
        "/memory/reconciliation/plans/plan%2F1/apply",
        "/memory/reconciliation/conflicts?limit=1000&status=OPEN",
        "/memory/reconciliation/conflicts/conflict%2F1",
        "/memory/reconciliation/conflicts/conflict%2F1/resolve",
    ]
    preview_payload = loads_json(calls[0].content)
    assert preview_payload["recall_limit"] == 100
    assert preview_payload["idempotency_key"] == "preview-key"
    assert preview_payload["candidate"]["candidate_id"] == "candidate/1"
    existing_payload = loads_json(calls[3].content)
    assert existing_payload == loads_json(calls[4].content)
    assert existing_payload["max_contexts"] == 250
    assert existing_payload["batch_size"] == 50
    assert existing_payload["recall_limit"] == 10
    assert existing_payload["include_archived"] is True
    assert loads_json(calls[6].content) == {"retry_failed": True}
    assert calls[7].url.params["status"] == "OPEN"
    assert calls[7].url.params["limit"] == "1000"
    assert loads_json(calls[9].content) == {
        "status": "RESOLVED_KEEP_BOTH",
        "resolution": "Both claims are valid in different temporal scopes.",
    }


def test_fastmcp_registers_memory_reconciliation_tools() -> None:
    """FastMCP should expose all durable reconciliation use cases."""
    client, _ = _client()
    server = build_mcp_server(client=client)

    tools = anyio.run(server.list_tools)
    names = {tool.name for tool in tools}

    assert {
        "alexandria_preview_memory_reconciliation",
        "alexandria_recall_memory_temporally",
        "alexandria_preview_reconciliation_memory_compact",
        "alexandria_preview_existing_memory_reconciliation",
        "alexandria_apply_existing_memory_reconciliation",
        "alexandria_get_memory_reconciliation_plan",
        "alexandria_apply_memory_reconciliation",
        "alexandria_list_memory_conflicts",
        "alexandria_get_memory_conflict",
        "alexandria_resolve_memory_conflict",
    } <= names
    assert {
        "alexandria_get_memory_reconciliation_result",
        "alexandria_mark_memory_conflict_reviewing",
    }.isdisjoint(names)
