"""Register Alexandria Core vault maintenance MCP tools."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import DEFAULT_CONTEXT_SEARCH_LIMIT
from app.mcp_server.tools.obsidian.obsidian_backend_gateway import (
    alexandria_search_vault,
)
from app.mcp_server.tools.obsidian.vault_maintenance_backend_gateway import (
    alexandria_get_graph_build_status,
    alexandria_get_graph_projection_status,
    alexandria_rebuild_graph_projection,
    alexandria_rebuild_note_graph,
    alexandria_reindex_vault,
    alexandria_validate_note_links,
    alexandria_vault_apply_moves,
    alexandria_vault_inventory,
    alexandria_vault_move_plan,
    alexandria_vault_path_search,
    alexandria_vault_review_apply_moves,
    alexandria_vault_review_move_plan,
    alexandria_vault_review_queue,
)
from app.shared.types.extra_types import JSONValue


def register_vault_maintenance_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register core vault indexing, graph, review, inventory, and move tools.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_reindex_vault")
    async def _tool_reindex_vault() -> JSONValue:
        """Rebuild the Obsidian vault index cache.

        Returns:
            JSONValue result produced by tool reindex vault.
        """
        return await alexandria_reindex_vault(api_client)

    @server.tool(name="alexandria_get_graph_projection_status")
    async def _tool_get_graph_projection_status() -> JSONValue:
        """Return optional graph projection status.

        Returns:
            JSONValue result produced by tool get graph projection status.
        """
        return await alexandria_get_graph_projection_status(api_client)

    @server.tool(name="alexandria_rebuild_graph_projection")
    async def _tool_rebuild_graph_projection() -> JSONValue:
        """Rebuild the optional graph projection from the current PostgreSQL index.

        Returns:
            JSONValue result produced by tool rebuild graph projection.
        """
        return await alexandria_rebuild_graph_projection(api_client)

    @server.tool(name="alexandria_get_graph_build_status")
    async def _tool_get_graph_build_status() -> JSONValue:
        """Return graph build status for snapshot projection diagnostics.

        Returns:
            JSONValue result produced by tool get graph build status.
        """
        return await alexandria_get_graph_build_status(api_client)

    @server.tool(name="alexandria_validate_note_links")
    async def _tool_validate_note_links(
        note_id: str | None = None,
        path: str | None = None,
        include_resolved_targets: bool = False,
    ) -> JSONValue:
        """Validate outgoing graph links for one indexed Obsidian note.

        Args:
            note_id: Identifier for note.
            path: Path used by this operation.
            include_resolved_targets: Whether to include resolved targets.

        Returns:
            JSONValue result produced by tool validate note links.
        """
        return await alexandria_validate_note_links(
            api_client,
            note_id=note_id,
            path=path,
            include_resolved_targets=include_resolved_targets,
        )

    @server.tool(name="alexandria_rebuild_note_graph")
    async def _tool_rebuild_note_graph(
        note_id: str | None = None,
        path: str | None = None,
        replace_existing_edges: bool = True,
    ) -> JSONValue:
        """Replace one note's indexed edges and activate a fresh graph snapshot.

        Args:
            note_id: Identifier for note.
            path: Path used by this operation.
            replace_existing_edges: Replace existing edges used by this operation.

        Returns:
            JSONValue result produced by tool rebuild note graph.
        """
        return await alexandria_rebuild_note_graph(
            api_client,
            note_id=note_id,
            path=path,
            replace_existing_edges=replace_existing_edges,
        )

    @server.tool(name="alexandria_search_vault")
    async def _tool_search_vault(
        query: str,
        limit: int = DEFAULT_CONTEXT_SEARCH_LIMIT,
        alexandria_type: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> JSONValue:
        """Search Alexandria-managed Obsidian Markdown notes.

        Args:
            query: Query used by this operation.
            limit: Maximum number of items to process or return.
            alexandria_type: Alexandria type used by this operation.
            project: Project used by this operation.
            tags: Tags used by this operation.

        Returns:
            JSONValue result produced by tool search vault.
        """
        return await alexandria_search_vault(
            api_client, query, limit, alexandria_type, project, tags
        )

    @server.tool(name="alexandria_vault_review_queue")
    async def _tool_vault_review_queue(
        project: str | None = None,
        scope_path: str | None = None,
        limit: int = 20,
    ) -> JSONValue:
        """List managed notes that need vault curation.

        Args:
            project: Project used by this operation.
            scope_path: Scope path used by this operation.
            limit: Maximum number of items to process or return.

        Returns:
            JSONValue result produced by tool vault review queue.
        """
        return await alexandria_vault_review_queue(
            api_client, project, scope_path, limit
        )

    @server.tool(name="alexandria_vault_review_move_plan")
    async def _tool_vault_review_move_plan(
        project: str | None = None,
        scope_path: str | None = None,
        limit: int = 20,
    ) -> JSONValue:
        """Build a dry-run move plan from vault review candidates.

        Args:
            project: Project used by this operation.
            scope_path: Scope path used by this operation.
            limit: Maximum number of items to process or return.

        Returns:
            JSONValue result produced by tool vault review move plan.
        """
        return await alexandria_vault_review_move_plan(
            api_client, project, scope_path, limit
        )

    @server.tool(name="alexandria_vault_review_apply_moves")
    async def _tool_vault_review_apply_moves(
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
            project: Project used by this operation.
            scope_path: Scope path used by this operation.
            limit: Maximum number of items to process or return.
            report_path: Report path used by this operation.
            reindex: Reindex used by this operation.
            verification_query: Verification query used by this operation.
            confirm_apply: Confirm apply used by this operation.

        Returns:
            JSONValue result produced by tool vault review apply moves.
        """
        return await alexandria_vault_review_apply_moves(
            api_client,
            project,
            scope_path,
            limit,
            report_path,
            reindex,
            verification_query,
            confirm_apply,
        )

    @server.tool(name="alexandria_vault_inventory")
    async def _tool_vault_inventory(scope_path: str | None = None) -> JSONValue:
        """Inventory managed Obsidian notes for core maintenance.

        Args:
            scope_path: Scope path used by this operation.

        Returns:
            JSONValue result produced by tool vault inventory.
        """
        return await alexandria_vault_inventory(api_client, scope_path)

    @server.tool(name="alexandria_vault_path_search")
    async def _tool_vault_path_search(
        query: str,
        scope_path: str | None = None,
    ) -> JSONValue:
        """Search managed Obsidian note paths and metadata.

        Args:
            query: Query used by this operation.
            scope_path: Scope path used by this operation.

        Returns:
            JSONValue result produced by tool vault path search.
        """
        return await alexandria_vault_path_search(api_client, query, scope_path)

    @server.tool(name="alexandria_vault_move_plan")
    async def _tool_vault_move_plan(moves: list[dict[str, str]]) -> JSONValue:
        """Build a dry-run safe move plan for explicit vault moves.

        Args:
            moves: Moves used by this operation.

        Returns:
            JSONValue result produced by tool vault move plan.
        """
        return await alexandria_vault_move_plan(api_client, moves)

    @server.tool(name="alexandria_vault_apply_moves")
    async def _tool_vault_apply_moves(
        moves: list[dict[str, str]],
        report_path: str | None = None,
        reindex: bool = True,
        verification_query: str | None = None,
    ) -> JSONValue:
        """Apply explicit safe vault moves through Alexandria Core maintenance.

        Args:
            moves: Moves used by this operation.
            report_path: Report path used by this operation.
            reindex: Reindex used by this operation.
            verification_query: Verification query used by this operation.

        Returns:
            JSONValue result produced by tool vault apply moves.
        """
        return await alexandria_vault_apply_moves(
            api_client,
            moves,
            report_path,
            reindex,
            verification_query,
        )
