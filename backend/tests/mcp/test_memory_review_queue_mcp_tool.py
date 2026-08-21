"""MCP contract tests for the durable memory review queue projection."""

from __future__ import annotations

import anyio
import httpx
from app.mcp_server.backend_api_client import AlexandriaApiClient, AlexandriaApiSettings
from app.mcp_server.server_runtime import build_mcp_server
from app.mcp_server.tools.reconciliation.memory_reconciliation_tools import (
    alexandria_list_memory_reconciliation_review_queue,
)
from app.shared.serialization.orjson_codec import dumps_json


def _client() -> tuple[AlexandriaApiClient, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json({"items": [], "total": 0}))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(base_url="http://backend:8000", timeout=12.0),
        transport=httpx.MockTransport(fake_transport),
    )
    return client, calls


def test_review_queue_gateway_clamps_limit_and_maps_endpoint() -> None:
    client, calls = _client()

    async def scenario() -> object:
        return await alexandria_list_memory_reconciliation_review_queue(
            client,
            limit=5000,
        )

    result = anyio.run(scenario)

    assert result == {"items": [], "total": 0}
    assert len(calls) == 1
    assert str(calls[0].url) == (
        "http://backend:8000/memory/reconciliation/review-queue?limit=1000"
    )


def test_fastmcp_registers_memory_review_queue_tool() -> None:
    client, _ = _client()
    server = build_mcp_server(client=client)

    names = {tool.name for tool in anyio.run(server.list_tools)}

    assert "alexandria_list_memory_reconciliation_review_queue" in names
