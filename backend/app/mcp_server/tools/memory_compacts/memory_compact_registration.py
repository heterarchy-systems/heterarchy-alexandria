"""Register read-only Memory Compact MCP tools."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.memory_compacts.memory_compact_tools import (
    alexandria_edit_memory_compact_draft,
    alexandria_get_current_memory_compact,
    alexandria_get_memory_compact,
    alexandria_list_memory_compact_artifacts,
    alexandria_mark_memory_compact_current,
    alexandria_review_memory_compact,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.shared.types.extra_types import JSONValue


def register_memory_compact_tools(
    server: MCPServer, api_client: AlexandriaApiClient
) -> None:
    """Register read-only compact discovery tools for requesting agents.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by callbacks.
    """

    @server.tool(name="alexandria_edit_memory_compact_draft")
    async def _tool_edit_memory_compact_draft(
        compact_id: str, markdown_body: str, expected_draft_hash: str
    ) -> JSONValue:
        """Replace a DRAFT body behind its exact read fence; re-review is mandatory.

        Args:
            compact_id: Canonical draft identity.
            markdown_body: Final semantic body to review.
            expected_draft_hash: Snapshot digest from the previous draft response.

        Returns:
            Updated draft with cleared review and promotion receipt.
        """
        return await alexandria_edit_memory_compact_draft(
            api_client, compact_id, markdown_body, expected_draft_hash
        )

    @server.tool(name="alexandria_list_memory_compact_artifacts")
    async def _tool_list_memory_compact_artifacts(
        project: str | None = None,
        status: MemoryCompactStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> JSONValue:
        """List durable Memory Compact artifacts.

        Args:
            project: Project used by this operation.
            status: Status value used by this operation.
            limit: Maximum number of items to process or return.
            offset: Pagination offset.

        Returns:
            JSONValue result produced by tool list memory compact artifacts.
        """
        return await alexandria_list_memory_compact_artifacts(
            api_client,
            project=project,
            status=status,
            limit=limit,
            offset=offset,
        )

    @server.tool(name="alexandria_get_current_memory_compact")
    async def _tool_get_current_memory_compact(
        project: str | None = None,
    ) -> JSONValue:
        """Read the current Memory Compact for a project.

        Args:
            project: Project used by this operation.

        Returns:
            JSONValue result produced by tool get current memory compact.
        """
        return await alexandria_get_current_memory_compact(api_client, project)

    @server.tool(name="alexandria_get_memory_compact")
    async def _tool_get_memory_compact(compact_id: str) -> JSONValue:
        """Read one selected Memory Compact by id.

        Args:
            compact_id: Identifier for compact.

        Returns:
            JSONValue result produced by tool get memory compact.
        """
        return await alexandria_get_memory_compact(api_client, compact_id)

    @server.tool(name="alexandria_review_memory_compact_draft")
    async def _tool_review_memory_compact_draft(compact_id: str) -> JSONValue:
        """Review one Memory Compact draft with the quality rubric.

        The returned receipt includes the evidence an apply needs; the
        apply tool's expected_review_hash binds that receipt to the exact
        reviewed body.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Backend Memory Compact review response.
        """
        return await alexandria_review_memory_compact(api_client, compact_id)

    @server.tool(name="alexandria_apply_reviewed_memory_compact")
    async def _tool_apply_reviewed_memory_compact(
        compact_id: str,
        expected_review_hash: str,
    ) -> JSONValue:
        """Apply a reviewed draft behind the review-receipt hash fence.

        Promotion is refused when the body or review drifted after the
        review; the previous CURRENT compact stays in place on refusal.

        Args:
            compact_id: Memory Compact identifier.
            expected_review_hash: Reviewed-receipt hash from the prior review.

        Returns:
            Backend Memory Compact response for the promoted compact.
        """
        return await alexandria_mark_memory_compact_current(
            api_client,
            compact_id,
            expected_review_hash=expected_review_hash,
        )
