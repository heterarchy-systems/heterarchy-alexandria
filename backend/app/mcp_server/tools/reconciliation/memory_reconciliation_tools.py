"""MCP HTTP tool adapters for memory reconciliation use cases."""

from __future__ import annotations

from urllib.parse import quote

from app.mcp_server.backend_api_client import AlexandriaApiClient
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
from app.shared.serialization.model_codec import schema_payload
from app.shared.types.extra_types import JSONObject, JSONValue


def _path_segment(value: str) -> str:
    """Return one percent-encoded URL path segment."""
    return quote(value, safe="")


async def alexandria_preview_memory_reconciliation(
    client: AlexandriaApiClient,
    candidate: MemoryCandidateRequest,
    idempotency_key: str | None = None,
    recall_limit: int = 20,
) -> JSONValue:
    """Create a durable reconciliation plan without canonical mutation.

    Args:
        client: Client.
        candidate: Candidate.
        idempotency_key: Idempotency key.
        recall_limit: Recall limit.

    Returns:
        JSONValue: Operation result.
    """
    payload: JSONObject = {
        "candidate": schema_payload(candidate, exclude_none=True),
        "recall_limit": min(max(int(recall_limit), 1), 100),
    }
    if idempotency_key is not None and idempotency_key.strip():
        payload["idempotency_key"] = idempotency_key.strip()
    return await client.post("/memory/reconciliation/preview", payload)


async def alexandria_recall_memory_temporally(
    client: AlexandriaApiClient,
    request: MemoryTemporalRecallHttpRequest,
) -> JSONValue:
    """Recall current, historical, or all matching memory states.

    Args:
        client: Client.
        request: Request.

    Returns:
        JSONValue: Operation result.
    """
    return await client.post(
        "/memory/reconciliation/recall",
        schema_payload(request, exclude_none=True),
    )


async def alexandria_preview_reconciliation_memory_compact(
    client: AlexandriaApiClient,
    request: MemoryTemporalRecallHttpRequest,
) -> JSONValue:
    """Preview reconciliation-aware Memory Compact fact buckets.

    Args:
        client: Client.
        request: Request.

    Returns:
        JSONValue: Operation result.
    """
    return await client.post(
        "/memory/reconciliation/compact/preview",
        schema_payload(request, exclude_none=True),
    )


async def alexandria_preview_existing_memory_reconciliation(
    client: AlexandriaApiClient,
    request: ExistingMemoryReconciliationHttpRequest,
) -> JSONValue:
    """Analyze existing memory without persisting backfill state or plans.

    Args:
        client: Client.
        request: Request.

    Returns:
        JSONValue: Operation result.
    """
    return await client.post(
        "/memory/reconciliation/existing/preview",
        schema_payload(request, exclude_none=True),
    )


async def alexandria_apply_existing_memory_reconciliation(
    client: AlexandriaApiClient,
    request: ExistingMemoryReconciliationHttpRequest,
) -> JSONValue:
    """Apply safe existing-memory temporal backfill and plan persistence.

    Args:
        client: Client.
        request: Request.

    Returns:
        JSONValue: Operation result.
    """
    return await client.post(
        "/memory/reconciliation/existing/apply",
        schema_payload(request, exclude_none=True),
    )


async def alexandria_get_memory_reconciliation_plan(
    client: AlexandriaApiClient,
    plan_id: str,
) -> JSONValue:
    """Read one persisted reconciliation plan.

    Args:
        client: Client.
        plan_id: Plan id.

    Returns:
        JSONValue: Operation result.
    """
    return await client.get(f"/memory/reconciliation/plans/{_path_segment(plan_id)}")


async def alexandria_list_memory_reconciliation_review_queue(
    client: AlexandriaApiClient,
    limit: int = 100,
) -> JSONValue:
    """List durable reconciliation plans requiring explicit review.

    Args:
        client: Client.
        limit: Limit.

    Returns:
        JSONValue: Operation result.
    """
    return await client.get(
        "/memory/reconciliation/review-queue",
        params={"limit": min(max(int(limit), 1), 1000)},
    )


async def alexandria_apply_memory_reconciliation(
    client: AlexandriaApiClient,
    plan_id: str,
    retry_failed: bool = False,
) -> JSONValue:
    """Apply one persisted reconciliation plan idempotently.

    Args:
        client: Client.
        plan_id: Plan id.
        retry_failed: Retry failed.

    Returns:
        JSONValue: Operation result.
    """
    return await client.post(
        f"/memory/reconciliation/plans/{_path_segment(plan_id)}/apply",
        {"retry_failed": retry_failed},
    )


async def alexandria_list_memory_conflicts(
    client: AlexandriaApiClient,
    status: MemoryConflictStatus | None = None,
    limit: int = 100,
) -> JSONValue:
    """List first-class memory conflicts without hiding resolved history.

    Args:
        client: Client.
        status: Status.
        limit: Limit.

    Returns:
        JSONValue: Operation result.
    """
    query: JSONObject = {"limit": min(max(int(limit), 1), 1000)}
    if status is not None:
        query["status"] = status.value
    return await client.get("/memory/reconciliation/conflicts", params=query)


async def alexandria_get_memory_conflict(
    client: AlexandriaApiClient,
    conflict_set_id: str,
) -> JSONValue:
    """Read one durable memory conflict set.

    Args:
        client: Client.
        conflict_set_id: Conflict set id.

    Returns:
        JSONValue: Operation result.
    """
    return await client.get(
        f"/memory/reconciliation/conflicts/{_path_segment(conflict_set_id)}"
    )


async def alexandria_resolve_memory_conflict(
    client: AlexandriaApiClient,
    conflict_set_id: str,
    status: MemoryConflictStatus,
    resolution: str,
) -> JSONValue:
    """Record an explicit final conflict resolution without deleting memory.

    Args:
        client: Client.
        conflict_set_id: Conflict set id.
        status: Status.
        resolution: Resolution.

    Returns:
        JSONValue: Operation result.
    """
    return await client.post(
        f"/memory/reconciliation/conflicts/{_path_segment(conflict_set_id)}/resolve",
        {"status": status.value, "resolution": resolution},
    )
