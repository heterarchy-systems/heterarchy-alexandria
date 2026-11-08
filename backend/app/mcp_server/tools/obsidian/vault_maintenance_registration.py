"""Register Alexandria Core vault maintenance MCP tools."""

from __future__ import annotations

from collections.abc import Sequence

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import DEFAULT_CONTEXT_SEARCH_LIMIT
from app.mcp_server.tools.obsidian.obsidian_backend_gateway import (
    ObsidianNoteBatchGateway,
)
from app.mcp_server.tools.obsidian.vault_maintenance_backend_gateway import (
    alexandria_get_graph_build_status,
    alexandria_get_graph_projection_status,
    alexandria_graph_list_issues,
    alexandria_rebuild_graph_projection,
    alexandria_rebuild_note_graph,
    alexandria_reindex_vault,
    alexandria_temporal_coverage,
    alexandria_validate_note_links,
    alexandria_vault_apply_moves,
    alexandria_vault_inventory,
    alexandria_vault_move_plan,
    alexandria_vault_path_search,
)
from app.obsidian.interface.schemas.obsidian.obsidian_temporal_coverage_schema import (
    ObsidianTemporalCoverageResponse,
)
from app.shared.types.extra_types import JSONObject, JSONValue


def register_vault_maintenance_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register core vault indexing, graph, review, inventory, and move tools.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_temporal_coverage")
    async def _tool_temporal_coverage(
        project: str,
        start_date: str,
        end_date: str,
        families: Sequence[str] | None = None,
        not_expected: Sequence[dict[str, str]] | None = None,
        timezone: str = "Asia/Seoul",
    ) -> ObsidianTemporalCoverageResponse:
        """Classify per-date report-family coverage without LLM inference.

        Args:
            project: Project identity whose packets are evaluated.
            start_date: Inclusive ISO range start.
            end_date: Inclusive ISO range end.
            families: Expected report families; empty reports observed only.
            not_expected: (family, date) entries that are NOT_EXPECTED.
            timezone: IANA timezone for open-day and week boundaries.

        Returns:
            Deterministic coverage matrix payload.
        """
        payload: JSONObject = {
            "project": project,
            "start_date": start_date,
            "end_date": end_date,
            "timezone": timezone,
        }
        if families:
            payload["families"] = list(families)
        if not_expected:
            payload["not_expected"] = [dict(entry) for entry in not_expected]
        return await alexandria_temporal_coverage(api_client, payload)

    @server.tool(name="alexandria_reindex_vault")
    async def _tool_reindex_vault() -> JSONValue:
        """Rebuild the Obsidian vault index cache.

        Returns:
            Vault reindex summary payload from the backend.
        """
        return await alexandria_reindex_vault(api_client)

    @server.tool(name="alexandria_get_graph_projection_status")
    async def _tool_get_graph_projection_status() -> JSONValue:
        """Return PostgreSQL graph projection status.

        Returns:
            Active graph projection snapshot and freshness metadata.
        """
        return await alexandria_get_graph_projection_status(api_client)

    @server.tool(name="alexandria_graph_list_issues")
    async def _tool_graph_list_issues(
        code: str | None = None,
        source_note_id: str | None = None,
        source_path: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> JSONValue:
        """List graph projection issues with exact source and target detail.

        Args:
            code: Optional issue code filter.
            source_note_id: Optional source note id filter.
            source_path: Optional source path filter.
            limit: Page size bound between 1 and 200.
            cursor: Keyset cursor from the previous page.

        Returns:
            Paginated graph projection issue list and next-page cursor.
        """
        return await alexandria_graph_list_issues(
            api_client,
            code=code,
            source_note_id=source_note_id,
            source_path=source_path,
            limit=limit,
            cursor=cursor,
        )

    @server.tool(name="alexandria_rebuild_graph_projection")
    async def _tool_rebuild_graph_projection() -> JSONValue:
        """Rebuild the PostgreSQL graph projection from the current PostgreSQL index.

        Returns:
            Rebuilt graph projection snapshot summary payload.
        """
        return await alexandria_rebuild_graph_projection(api_client)

    @server.tool(name="alexandria_get_graph_build_status")
    async def _tool_get_graph_build_status() -> JSONValue:
        """Return graph build status for snapshot projection diagnostics.

        Returns:
            Graph projection build diagnostic status payload.
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
            note_id: Stable identifier of the note to validate.
            path: Vault-relative Markdown path of the note to validate.
            include_resolved_targets: Whether to include resolved target details.

        Returns:
            Outgoing link validation report for the selected note.
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
            note_id: Stable identifier of the note whose edges are rebuilt.
            path: Vault-relative Markdown path of the note whose edges are rebuilt.
            replace_existing_edges: Whether to replace previously indexed outgoing edges.

        Returns:
            Single-note graph rebuild and projection refresh result.
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
            query: Full-text or semantic search query string.
            limit: Maximum number of matching notes to return.
            alexandria_type: Optional managed note type filter.
            project: Optional project slug filter.
            tags: Optional list of required note tags.

        Returns:
            Compacted vault search results payload.
        """
        return await ObsidianNoteBatchGateway.search_vault(
            api_client, query, limit, alexandria_type, project, tags
        )

    @server.tool(name="alexandria_vault_inventory")
    async def _tool_vault_inventory(scope_path: str | None = None) -> JSONValue:
        """Inventory managed Obsidian notes for core maintenance.

        Args:
            scope_path: Optional vault-relative directory prefix restricting the inventory.

        Returns:
            Managed note inventory summary for the requested vault scope.
        """
        return await alexandria_vault_inventory(api_client, scope_path)

    @server.tool(name="alexandria_vault_path_search")
    async def _tool_vault_path_search(
        query: str,
        scope_path: str | None = None,
    ) -> JSONValue:
        """Search managed Obsidian note paths and metadata.

        Args:
            query: Path or metadata substring query.
            scope_path: Optional vault-relative directory prefix restricting the search.

        Returns:
            Matching vault note paths and metadata entries.
        """
        return await alexandria_vault_path_search(api_client, query, scope_path)

    @server.tool(name="alexandria_vault_move_plan")
    async def _tool_vault_move_plan(moves: list[dict[str, str]]) -> JSONValue:
        """Build a dry-run safe move plan for explicit vault moves.

        Args:
            moves: Source-to-destination vault path move specifications.

        Returns:
            Dry-run move plan detailing link rewrites and collision checks.
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
            moves: Source-to-destination vault path move specifications.
            report_path: Optional vault-relative path for persisting the move report.
            reindex: Whether to reindex modified notes after applying moves.
            verification_query: Optional search query executed after reindexing.

        Returns:
            Applied vault move receipt with link update and verification outcomes.
        """
        return await alexandria_vault_apply_moves(
            api_client,
            moves,
            report_path,
            reindex,
            verification_query,
        )
