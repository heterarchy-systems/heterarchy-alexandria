"""MCP boundary regressions for the bounded maintenance DLQ lifecycle."""

from __future__ import annotations

import anyio
import httpx

from app.mcp_server.backend_api_client import (
    AlexandriaApiClient,
    AlexandriaApiSettings,
)
from app.mcp_server.server_runtime import build_mcp_server
from app.mcp_server.tools.operations.maintenance_backend_gateway import (
    alexandria_maintenance_dlq_inspect,
    alexandria_maintenance_dlq_reconcile,
    alexandria_maintenance_dlq_retire,
    alexandria_maintenance_dlq_retry,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json


def _client() -> tuple[AlexandriaApiClient, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json({"ok": True}))

    return (
        AlexandriaApiClient(
            AlexandriaApiSettings(base_url="http://backend:8000", timeout=12.0),
            transport=httpx.MockTransport(fake_transport),
        ),
        calls,
    )


def test_dlq_inspect_reconcile_and_retry_keep_entry_id_in_one_path_segment() -> None:
    client, calls = _client()

    anyio.run(alexandria_maintenance_dlq_inspect, client, " 7/0 ")
    anyio.run(
        alexandria_maintenance_dlq_retry,
        client,
        " 7/0 ",
        True,
        "review",
    )
    anyio.run(alexandria_maintenance_dlq_reconcile, client, " 7/0 ")

    assert str(calls[0].url) == (
        "http://backend:8000/operations/maintenance/dead-letters/7%2F0"
    )
    assert str(calls[1].url) == (
        "http://backend:8000/operations/maintenance/dead-letters/7%2F0/retry"
    )
    assert loads_json(calls[1].content) == {"dry_run": True, "reason": "review"}
    assert str(calls[2].url).endswith("/dead-letters/7%2F0/reconcile")


def test_dlq_retire_sends_bounded_provenance_fields() -> None:
    client, calls = _client()

    anyio.run(
        alexandria_maintenance_dlq_retire,
        client,
        "7-0",
        "already reviewed",
        "NON_RETRYABLE",
        "operator",
    )

    assert calls[0].method == "POST"
    assert str(calls[0].url).endswith("/dead-letters/7-0/retire")
    assert loads_json(calls[0].content) == {
        "reason": "already reviewed",
        "classification": "NON_RETRYABLE",
        "retired_by": "operator",
    }


def test_mcp_registers_dlq_lifecycle_tools() -> None:
    client, _ = _client()
    server = build_mcp_server(client=client)
    names = {tool.name for tool in anyio.run(server.list_tools)}
    assert {
        "alexandria_maintenance_dlq_inspect",
        "alexandria_maintenance_dlq_retry",
        "alexandria_maintenance_dlq_reconcile",
        "alexandria_maintenance_dlq_retire",
    } <= names
