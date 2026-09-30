"""MCP HTTP gateways for graph orphan census and suggestions."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.shared.types.extra_types import JSONObject, JSONValue


async def alexandria_list_graph_orphans(
    client: AlexandriaApiClient,
    payload: JSONObject,
) -> JSONValue:
    """List bounded graph orphan debt with durable census metadata."""
    return await client.post("/obsidian/graph/orphans", payload)


async def alexandria_acknowledge_graph_orphan(
    client: AlexandriaApiClient,
    payload: JSONObject,
) -> JSONValue:
    """Persist one explicit orphan acknowledgement."""
    return await client.post("/obsidian/graph/orphans/acknowledge", payload)


async def alexandria_get_graph_orphan_status(
    client: AlexandriaApiClient,
    payload: JSONObject,
) -> JSONValue:
    """Read one exact current orphan status and durable census history."""
    return await client.post("/obsidian/graph/orphans/status", payload)


async def alexandria_suggest_graph_relations(
    client: AlexandriaApiClient,
    payload: JSONObject,
) -> JSONValue:
    """Return deterministic suggestion-only graph relation evidence."""
    return await client.post("/obsidian/graph/orphans/suggest-relations", payload)
