"""Vault maintenance MCP HTTP gateway functions."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import (
    _move_payloads,
)
from app.shared.types.extra_types import JSONObject, JSONValue


async def alexandria_reindex_vault(client: AlexandriaApiClient) -> JSONValue:
    """Rebuild the Obsidian vault index cache.

    Args:
        client: Backend HTTP client.

    Returns:
        Backend reindex response.
    """
    return await client.post("/obsidian/index/rebuild", {})


async def alexandria_get_graph_projection_status(
    client: AlexandriaApiClient,
) -> JSONValue:
    """Return PostgreSQL graph projection status.

    Args:
        client: Backend HTTP client.

    Returns:
        Backend graph projection status response.
    """
    return await client.get("/obsidian/graph/projection/status")


async def alexandria_graph_list_issues(
    client: AlexandriaApiClient,
    code: str | None = None,
    source_note_id: str | None = None,
    source_path: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> JSONValue:
    """List graph projection issues with exact source and target detail.

    Args:
        client: Backend HTTP client.
        code: Optional issue code filter.
        source_note_id: Optional source note id filter.
        source_path: Optional source path filter.
        limit: Page size bound.
        cursor: Keyset cursor from the previous page.

    Returns:
        Backend graph issue list response.
    """
    params: JSONObject = {}
    if code is not None:
        params["code"] = code
    if source_note_id is not None:
        params["source_note_id"] = source_note_id
    if source_path is not None:
        params["source_path"] = source_path
    if limit != 50:
        params["limit"] = str(limit)
    if cursor is not None:
        params["cursor"] = cursor
    return await client.get("/obsidian/graph/issues", params=params)


async def alexandria_rebuild_graph_projection(
    client: AlexandriaApiClient,
) -> JSONValue:
    """Rebuild the PostgreSQL graph projection from the current PostgreSQL index.

    Args:
        client: Backend HTTP client.

    Returns:
        Backend graph projection rebuild response.
    """
    return await client.post("/obsidian/graph/projection/rebuild", {})


async def alexandria_get_graph_build_status(
    client: AlexandriaApiClient,
) -> JSONValue:
    """Return graph build status for snapshot projection diagnostics.

    Args:
        client: Backend HTTP client.

    Returns:
        Backend graph build/status response.
    """
    return await client.get("/obsidian/graph/build/status")


async def alexandria_validate_note_links(
    client: AlexandriaApiClient,
    note_id: str | None = None,
    path: str | None = None,
    include_resolved_targets: bool = False,
) -> JSONValue:
    """Validate outgoing graph links for one indexed Obsidian note.

    Args:
        client: Backend HTTP client.
        note_id: Optional stable note id selector.
        path: Optional vault-relative exact path selector.
        include_resolved_targets: Include resolved edge details when true.

    Returns:
        Backend per-note graph link validation response.
    """
    query: JSONObject = {
        "include_resolved_targets": include_resolved_targets,
    }
    if note_id is not None:
        query["note_id"] = note_id
    if path is not None:
        query["path"] = path
    return await client.get("/obsidian/graph/notes/validate-links", params=query)


async def alexandria_rebuild_note_graph(
    client: AlexandriaApiClient,
    note_id: str | None = None,
    path: str | None = None,
    replace_existing_edges: bool = True,
) -> JSONValue:
    """Reparse one note's cached edges and activate a fresh graph snapshot.

    Args:
        client: Value supplied to alexandria_rebuild_note_graph.
        note_id: Value supplied to alexandria_rebuild_note_graph.
        path: Value supplied to alexandria_rebuild_note_graph.
        replace_existing_edges: Value supplied to alexandria_rebuild_note_graph.

    Returns:
        Result produced by alexandria_rebuild_note_graph.
    """
    query: JSONObject = {"replace_existing_edges": replace_existing_edges}
    if note_id is not None:
        query["note_id"] = note_id
    if path is not None:
        query["path"] = path
    return await client.post_query("/obsidian/graph/notes/rebuild", params=query)


async def alexandria_vault_inventory(
    client: AlexandriaApiClient,
    scope_path: str | None = None,
) -> JSONValue:
    """Inventory managed Obsidian notes for Alexandria Core maintenance."""
    payload: JSONObject = {}
    if scope_path is not None:
        payload["scope_path"] = scope_path
    return await client.post("/obsidian/vault/inventory", payload)


async def alexandria_vault_path_search(
    client: AlexandriaApiClient,
    query: str,
    scope_path: str | None = None,
) -> JSONValue:
    """Search managed Obsidian note paths and metadata."""
    payload: JSONObject = {"query": query}
    if scope_path is not None:
        payload["scope_path"] = scope_path
    return await client.post("/obsidian/vault/path-search", payload)


async def alexandria_vault_move_plan(
    client: AlexandriaApiClient,
    moves: list[dict[str, str]],
) -> JSONValue:
    """Build a dry-run safe move plan for explicit vault moves."""
    return await client.post(
        "/obsidian/vault/move-plan",
        {"moves": _move_payloads(moves)},
    )


async def alexandria_vault_apply_moves(
    client: AlexandriaApiClient,
    moves: list[dict[str, str]],
    report_path: str | None = None,
    reindex: bool = True,
    verification_query: str | None = None,
) -> JSONValue:
    """Apply explicit safe vault moves through Alexandria Core maintenance."""
    payload: JSONObject = {
        "moves": _move_payloads(moves),
        "reindex": reindex,
    }
    if report_path is not None:
        payload["report_path"] = report_path
    if verification_query is not None:
        payload["verification_query"] = verification_query
    return await client.post("/obsidian/vault/apply-moves", payload)
