"""Operator-only orchestration for bounded Context retrieval diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.application.contexts.diagnostics.context_search_trace import (
    ContextSearchExplainResult,
)
from app.memory.application.contexts.records.context_service_ports import (
    ContextSearchDiagnosticsPort,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    MemoryFunction,
    RagStrategy,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationalRetrievalDiagnosticsQuery:
    """Validated application command for one retrieval flight-recorder execution."""

    query: str
    strategy: RagStrategy = RagStrategy.HYBRID
    limit: int = 5
    project: str | None = None
    kind: ContextKind | None = None
    include_scopes: tuple[ContextScope, ...] = ()
    workspace_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    include_lifecycle_statuses: tuple[ContextRecallLifecycleStatus, ...] = ()
    prefer_memory_functions: tuple[MemoryFunction, ...] = ()


class OperationalRetrievalDiagnosticsService:
    """Execute one normal Context search while collecting bounded debug evidence."""

    def __init__(self, context_service: ContextSearchDiagnosticsPort) -> None:
        """Create the operator diagnostics service.

        Args:
            context_service: Context-owned explain-search capability boundary.
        """
        self._context_service = context_service

    async def explain(
        self,
        request: OperationalRetrievalDiagnosticsQuery,
    ) -> ContextSearchExplainResult:
        """Execute one retrieval flight-recorder request.

        Args:
            request: Strict application command containing recall filters.

        Returns:
            Normal Context pack paired with bounded execution diagnostics.

        Raises:
            ValueError: If the request limit is outside the supported operator bound.
        """
        if request.limit < 1 or request.limit > 50:
            raise ValueError("RETRIEVAL_DIAGNOSTICS_LIMIT_INVALID: limit must be 1..50")
        return await self._context_service.explain_search(
            query=request.query,
            strategy=request.strategy,
            limit=request.limit,
            project=request.project,
            kind=request.kind,
            include_scopes=list(request.include_scopes),
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            user_id=request.user_id,
            session_id=request.session_id,
            include_lifecycle_statuses=list(request.include_lifecycle_statuses),
            prefer_memory_functions=list(request.prefer_memory_functions),
        )
