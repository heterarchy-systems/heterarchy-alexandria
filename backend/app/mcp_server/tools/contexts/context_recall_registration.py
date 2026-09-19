"""Register Context search, brief, and recall MCP tools."""

from __future__ import annotations

from collections.abc import Sequence

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import (
    DEFAULT_CONTEXT_SEARCH_LIMIT,
    DEFAULT_CONTEXT_SEARCH_STRATEGY,
    _bounded_search_limit,
)
from app.mcp_server.tools.contexts.context_backend_gateway import (
    alexandria_context_brief,
    alexandria_search,
)
from app.memory.application.retrieval.context_brief import (
    MAX_CONTEXT_BRIEF_BYTES,
    MAX_CONTEXTS_PER_BRIEF,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    MemoryFunction,
    RagStrategy,
)
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextBriefRequest,
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
        prefer_memory_functions: list[MemoryFunction] | None = None,
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
            prefer_memory_functions: Optional soft functional-memory preference.

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
                prefer_memory_functions=(
                    [] if prefer_memory_functions is None else prefer_memory_functions
                ),
            ),
        )


def register_context_brief_tool(
    server: MCPServer, api_client: AlexandriaApiClient
) -> None:
    """Register the budgeted Context brief MCP tool.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_context_brief")
    async def _tool_context_brief(
        query: str,
        byte_budget: int = MAX_CONTEXT_BRIEF_BYTES,
        record_budget: int = MAX_CONTEXTS_PER_BRIEF,
        previously_delivered: Sequence[Sequence[str]] | None = None,
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
        prefer_memory_functions: list[MemoryFunction] | None = None,
    ) -> JSONValue:
        """Build a budgeted model-delivery context brief with repetition control.

        The brief is a read-only projection of the normal search path: it
        carries no id of its own, records no change-log entries, and reports
        exact byte accounting with omissions and re-fetch references.

        Args:
            query: Search query.
            byte_budget: Maximum rendered utf-8 byte count.
            record_budget: Maximum number of delivered context entries.
            previously_delivered: Ordered ``(context_id, content_hash)`` pairs
                delivered to the same consumer by earlier briefs.
            limit: Maximum number of matching contexts retrieved.
            strategy: Retrieval strategy.
            project: Optional project filter.
            kind: Optional context kind filter.
            include_scopes: Optional recall scopes.
            workspace_id: Optional workspace filter.
            agent_id: Optional agent filter.
            user_id: Optional user filter.
            session_id: Optional session filter.
            include_lifecycle_statuses: Optional administrative lifecycle filter.
            prefer_memory_functions: Optional soft functional-memory preference.

        Returns:
            Backend budgeted brief response payload.
        """
        pairs = [
            (str(pair[0]), str(pair[1]))
            for pair in (previously_delivered or ())
            if len(pair) == 2
        ]
        return await alexandria_context_brief(
            api_client,
            ContextBriefRequest(
                query=query,
                byte_budget=byte_budget,
                record_budget=record_budget,
                previously_delivered=pairs,
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
                prefer_memory_functions=(
                    [] if prefer_memory_functions is None else prefer_memory_functions
                ),
            ),
        )
