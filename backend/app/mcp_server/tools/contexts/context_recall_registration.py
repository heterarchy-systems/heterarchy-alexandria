"""Register Context search and recall MCP tools."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import (
    DEFAULT_CONTEXT_SEARCH_LIMIT,
    DEFAULT_CONTEXT_SEARCH_STRATEGY,
    _bounded_search_limit,
)
from app.mcp_server.tools.contexts.context_backend_gateway import alexandria_search
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    RagStrategy,
)
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextSearchRequest,
)
from app.shared.types.extra_types import JSONValue


def register_context_recall_tools(
    server: MCPServer, api_client: AlexandriaApiClient
) -> None:
    """Register Context search and recall MCP tools.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_search")
    async def _tool_search(
        query: str,
        limit: int = DEFAULT_CONTEXT_SEARCH_LIMIT,
        strategy: RagStrategy = DEFAULT_CONTEXT_SEARCH_STRATEGY,
        project: str | None = None,
        kind: ContextKind | None = None,
        include_scopes: list[ContextScope] | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        include_lifecycle_statuses: list[ContextRecallLifecycleStatus] | None = None,
    ) -> JSONValue:
        """Search Context Vault and return a Context Pack.

        Args:
            query: Search query.
            limit: Maximum number of matching contexts.
            strategy: Retrieval strategy.
            project: Optional project filter.
            kind: Optional context kind filter.
            include_scopes: Optional recall scopes.
            workspace_id: Optional workspace filter.
            agent_id: Optional agent filter.
            user_id: Optional user filter.
            session_id: Optional session filter.
            include_lifecycle_statuses: Optional administrative lifecycle filter.

        Returns:
            Backend Context Pack response.
        """
        return await alexandria_search(
            api_client,
            ContextSearchRequest(
                query=query,
                limit=_bounded_search_limit(limit),
                strategy=strategy,
                project=project,
                kind=kind,
                include_scopes=[] if include_scopes is None else include_scopes,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                session_id=session_id,
                include_lifecycle_statuses=(
                    []
                    if include_lifecycle_statuses is None
                    else include_lifecycle_statuses
                ),
            ),
        )
