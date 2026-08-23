"""MCPServer registration for memory reconciliation tools."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.reconciliation.memory_reconciliation_tools import (
    alexandria_apply_existing_memory_reconciliation,
    alexandria_apply_memory_reconciliation,
    alexandria_get_memory_conflict,
    alexandria_get_memory_reconciliation_plan,
    alexandria_list_memory_conflicts,
    alexandria_list_memory_reconciliation_review_queue,
    alexandria_preview_existing_memory_reconciliation,
    alexandria_preview_memory_reconciliation,
    alexandria_preview_reconciliation_memory_compact,
    alexandria_recall_memory_temporally,
    alexandria_resolve_memory_conflict,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryConflictStatus
from app.memory.interface.schemas.reconciliation.candidate.memory_reconciliation_candidate_request_schema import (
    MemoryCandidateRequest,
)
from app.memory.interface.schemas.reconciliation.existing.memory_existing_reconciliation_request_schema import (
    ExistingMemoryReconciliationHttpRequest,
)
from app.memory.interface.schemas.reconciliation.temporal.memory_reconciliation_temporal_request_schema import (
    MemoryTemporalRecallHttpRequest,
)
from app.shared.types.extra_types import JSONValue


def register_memory_reconciliation_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register reconciliation tools on one MCPServer server.

    Args:
        server: Server.
        api_client: Api client.
    """

    @server.tool(name="alexandria_preview_memory_reconciliation")
    async def _preview_memory_reconciliation(
        candidate: MemoryCandidateRequest,
        idempotency_key: str | None = None,
        recall_limit: int = 20,
    ) -> JSONValue:
        """Preview and persist a reconciliation plan without mutation.

        Args:
            candidate: Candidate used by this operation.
            idempotency_key: Idempotency key used by this operation.
            recall_limit: Recall limit used by this operation.

        Returns:
            JSONValue result produced by preview memory reconciliation.
        """
        return await alexandria_preview_memory_reconciliation(
            api_client,
            candidate,
            idempotency_key=idempotency_key,
            recall_limit=recall_limit,
        )

    @server.tool(name="alexandria_recall_memory_temporally")
    async def _recall_memory_temporally(
        request: MemoryTemporalRecallHttpRequest,
    ) -> JSONValue:
        """Recall current, historical, or all matching memory states.

        Args:
            request: Validated request for this operation.

        Returns:
            JSONValue result produced by recall memory temporally.
        """
        return await alexandria_recall_memory_temporally(
            api_client,
            request,
        )

    @server.tool(name="alexandria_preview_reconciliation_memory_compact")
    async def _preview_reconciliation_memory_compact(
        request: MemoryTemporalRecallHttpRequest,
    ) -> JSONValue:
        """Preview safe Memory Compact fact buckets and blockers.

        Args:
            request: Validated request for this operation.

        Returns:
            JSONValue result produced by preview reconciliation memory compact.
        """
        return await alexandria_preview_reconciliation_memory_compact(
            api_client,
            request,
        )

    @server.tool(name="alexandria_preview_existing_memory_reconciliation")
    async def _preview_existing_memory_reconciliation(
        request: ExistingMemoryReconciliationHttpRequest,
    ) -> JSONValue:
        """Analyze existing memory without persisting backfill state or plans.

        Args:
            request: Validated request for this operation.

        Returns:
            JSONValue result produced by preview existing memory reconciliation.
        """
        return await alexandria_preview_existing_memory_reconciliation(
            api_client,
            request,
        )

    @server.tool(name="alexandria_apply_existing_memory_reconciliation")
    async def _apply_existing_memory_reconciliation(
        request: ExistingMemoryReconciliationHttpRequest,
    ) -> JSONValue:
        """Apply safe temporal backfill and persist reviewable plans.

        Args:
            request: Validated request for this operation.

        Returns:
            JSONValue result produced by apply existing memory reconciliation.
        """
        return await alexandria_apply_existing_memory_reconciliation(
            api_client,
            request,
        )

    @server.tool(name="alexandria_get_memory_reconciliation_plan")
    async def _get_memory_reconciliation_plan(plan_id: str) -> JSONValue:
        """Read one persisted reconciliation plan.

        Args:
            plan_id: Identifier for plan.

        Returns:
            Requested memory reconciliation plan.
        """
        return await alexandria_get_memory_reconciliation_plan(
            api_client,
            plan_id,
        )

    @server.tool(name="alexandria_list_memory_reconciliation_review_queue")
    async def _list_memory_reconciliation_review_queue(
        limit: int = 100,
    ) -> JSONValue:
        """List persisted UNKNOWN and other review-required plans.

        Args:
            limit: Maximum number of items to process or return.

        Returns:
            Requested memory reconciliation review queue.
        """
        return await alexandria_list_memory_reconciliation_review_queue(
            api_client,
            limit=limit,
        )

    @server.tool(name="alexandria_apply_memory_reconciliation")
    async def _apply_memory_reconciliation(
        plan_id: str,
        retry_failed: bool = False,
    ) -> JSONValue:
        """Apply one reconciliation plan idempotently.

        Args:
            plan_id: Identifier for plan.
            retry_failed: Retry failed used by this operation.

        Returns:
            JSONValue result produced by apply memory reconciliation.
        """
        return await alexandria_apply_memory_reconciliation(
            api_client,
            plan_id,
            retry_failed=retry_failed,
        )

    @server.tool(name="alexandria_list_memory_conflicts")
    async def _list_memory_conflicts(
        status: MemoryConflictStatus | None = None,
        limit: int = 100,
    ) -> JSONValue:
        """List open or resolved memory conflicts.

        Args:
            status: Status value used by this operation.
            limit: Maximum number of items to process or return.

        Returns:
            Requested memory conflicts.
        """
        return await alexandria_list_memory_conflicts(
            api_client,
            status=status,
            limit=limit,
        )

    @server.tool(name="alexandria_get_memory_conflict")
    async def _get_memory_conflict(conflict_set_id: str) -> JSONValue:
        """Read one memory conflict set.

        Args:
            conflict_set_id: Identifier for conflict set.

        Returns:
            Requested memory conflict.
        """
        return await alexandria_get_memory_conflict(
            api_client,
            conflict_set_id,
        )

    @server.tool(name="alexandria_resolve_memory_conflict")
    async def _resolve_memory_conflict(
        conflict_set_id: str,
        status: MemoryConflictStatus,
        resolution: str,
    ) -> JSONValue:
        """Record an explicit final conflict resolution.

        Args:
            conflict_set_id: Identifier for conflict set.
            status: Status value used by this operation.
            resolution: Resolution used by this operation.

        Returns:
            Resolved memory conflict.
        """
        return await alexandria_resolve_memory_conflict(
            api_client,
            conflict_set_id,
            status=status,
            resolution=resolution,
        )
