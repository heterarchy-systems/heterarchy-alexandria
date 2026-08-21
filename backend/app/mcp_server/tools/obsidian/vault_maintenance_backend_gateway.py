"""Librarian review and vault maintenance MCP HTTP gateway functions."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import (
    _move_payloads,
)
from app.mcp_server.type_validate.obsidian.librarian_review_gateway_contracts import (
    empty_review_apply_payload,
    review_apply_confirmation_required_payload,
    review_move_plan_has_moves,
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
    """Return optional graph projection status.

    Args:
        client: Backend HTTP client.

    Returns:
        Backend graph projection status response.
    """
    return await client.get("/obsidian/graph/projection/status")


async def alexandria_rebuild_graph_projection(
    client: AlexandriaApiClient,
) -> JSONValue:
    """Rebuild the optional graph projection from the current PostgreSQL index.

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


async def alexandria_vault_review_queue(
    client: AlexandriaApiClient,
    project: str | None = None,
    scope_path: str | None = None,
    limit: int = 20,
) -> JSONValue:
    """List managed notes that need vault curation.

    Args:
        client: Backend HTTP client.
        project: Optional project filter.
        scope_path: Optional vault-relative scope.
        limit: Maximum candidates to return.

    Returns:
        Backend review queue response.
    """
    payload: JSONObject = {"limit": min(max(int(limit), 1), 200)}
    if project is not None:
        payload["project"] = project
    if scope_path is not None:
        payload["scope_path"] = scope_path
    return await client.post("/obsidian/librarian/review-queue", payload)


async def alexandria_vault_review_move_plan(
    client: AlexandriaApiClient,
    project: str | None = None,
    scope_path: str | None = None,
    limit: int = 20,
) -> JSONValue:
    """Build a dry-run move plan from vault review candidates.

    Args:
        client: Backend HTTP client.
        project: Optional project filter.
        scope_path: Optional vault-relative scope.
        limit: Maximum candidates to plan from.

    Returns:
        Backend safe move-plan response.
    """
    payload: JSONObject = {"limit": min(max(int(limit), 1), 200)}
    if project is not None:
        payload["project"] = project
    if scope_path is not None:
        payload["scope_path"] = scope_path
    return await client.post("/obsidian/librarian/review-queue/move-plan", payload)


async def alexandria_vault_review_apply_moves(
    client: AlexandriaApiClient,
    project: str | None = None,
    scope_path: str | None = None,
    limit: int = 20,
    report_path: str | None = None,
    reindex: bool = True,
    verification_query: str | None = None,
    confirm_apply: bool = False,
) -> JSONValue:
    """Apply safe moves generated from vault review candidates.

    Args:
        client: Backend HTTP client.
        project: Optional project filter.
        scope_path: Optional vault-relative scope.
        limit: Maximum candidates to apply.
        report_path: Optional report path stem.
        reindex: Whether to reindex after moving.
        verification_query: Optional verification search query.
        confirm_apply: Required confirmation when the move plan has moves.

    Returns:
        Backend safe move application report.
    """
    move_plan = await alexandria_vault_review_move_plan(
        client,
        project=project,
        scope_path=scope_path,
        limit=limit,
    )
    if not review_move_plan_has_moves(move_plan):
        return empty_review_apply_payload(move_plan)
    if not confirm_apply:
        return review_apply_confirmation_required_payload(move_plan)

    payload: JSONObject = {
        "limit": min(max(int(limit), 1), 200),
        "reindex": reindex,
    }
    if project is not None:
        payload["project"] = project
    if scope_path is not None:
        payload["scope_path"] = scope_path
    if report_path is not None:
        payload["report_path"] = report_path
    if verification_query is not None:
        payload["verification_query"] = verification_query
    return await client.post("/obsidian/librarian/review-queue/apply-moves", payload)


async def alexandria_vault_inventory(
    client: AlexandriaApiClient,
    scope_path: str | None = None,
) -> JSONValue:
    """Inventory managed Obsidian notes for Alexandria Core maintenance.

    Args:
        client: Backend HTTP client.
        scope_path: Optional vault-relative scope.

    Returns:
        Backend inventory response.
    """
    payload: JSONObject = {}
    if scope_path is not None:
        payload["scope_path"] = scope_path
    return await client.post("/obsidian/librarian/vault/inventory", payload)


async def alexandria_vault_path_search(
    client: AlexandriaApiClient,
    query: str,
    scope_path: str | None = None,
) -> JSONValue:
    """Search managed Obsidian note paths and metadata.

    Args:
        client: Backend HTTP client.
        query: Keyword/path fragment.
        scope_path: Optional vault-relative scope.

    Returns:
        Backend inventory response containing matching notes.
    """
    payload: JSONObject = {"query": query}
    if scope_path is not None:
        payload["scope_path"] = scope_path
    return await client.post("/obsidian/librarian/vault/path-search", payload)


async def alexandria_vault_move_plan(
    client: AlexandriaApiClient,
    moves: list[dict[str, str]],
) -> JSONValue:
    """Build a dry-run safe move plan for explicit vault moves.

    Args:
        client: Backend HTTP client.
        moves: Explicit source/destination/reason move payloads.

    Returns:
        Backend safe move-plan response.
    """
    return await client.post(
        "/obsidian/librarian/vault/move-plan",
        {"moves": _move_payloads(moves)},
    )


async def alexandria_vault_apply_moves(
    client: AlexandriaApiClient,
    moves: list[dict[str, str]],
    report_path: str | None = None,
    reindex: bool = True,
    verification_query: str | None = None,
) -> JSONValue:
    """Apply explicit safe vault moves through Alexandria Core maintenance.

    Args:
        client: Backend HTTP client.
        moves: Explicit source/destination/reason move payloads.
        report_path: Optional report path stem.
        reindex: Whether to reindex after moving.
        verification_query: Optional verification query.

    Returns:
        Backend safe move application report.
    """
    payload: JSONObject = {
        "moves": _move_payloads(moves),
        "reindex": reindex,
    }
    if report_path is not None:
        payload["report_path"] = report_path
    if verification_query is not None:
        payload["verification_query"] = verification_query
    return await client.post("/obsidian/librarian/vault/apply-moves", payload)
