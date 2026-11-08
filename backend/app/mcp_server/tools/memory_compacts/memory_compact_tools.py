"""MCP HTTP tool adapters for Memory Compact artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import quote

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.shared.types.extra_types import JSONObject, JSONValue


async def alexandria_list_memory_compact_artifacts(
    client: AlexandriaApiClient,
    project: str | None = None,
    status: MemoryCompactStatus | None = None,
    limit: int = 20,
    offset: int = 0,
) -> JSONValue:
    """List durable Memory Compact artifacts.

    Args:
        client: Backend HTTP client.
        project: Optional project filter.
        status: Optional lifecycle status filter.
        limit: Maximum number of rows to return.
        offset: Number of rows to skip.

    Returns:
        Backend Memory Compact list response.
    """
    query: JSONObject = {
        "limit": min(max(limit, 1), 50),
        "offset": max(offset, 0),
    }
    if project is not None:
        query["project"] = project
    if status is not None:
        query["status"] = status.value
    return await client.get("/memory/compacts", params=query)


async def alexandria_create_memory_compact(
    client: AlexandriaApiClient,
    covered_from: str,
    covered_to: str,
    markdown_body: str,
    project: str | None = None,
    status: MemoryCompactStatus = MemoryCompactStatus.DRAFT,
    source_refs: Sequence[Mapping[str, JSONValue]] | None = None,
) -> JSONValue:
    """Create a durable Memory Compact artifact.

    Args:
        client: Backend HTTP client.
        covered_from: Inclusive coverage start timestamp.
        covered_to: Exclusive coverage end timestamp.
        markdown_body: Durable Markdown body for the compact.
        project: Optional project filter.
        status: Compact lifecycle status.
        source_refs: Optional source references for CURRENT compacts.

    Returns:
        Backend Memory Compact response.
    """
    payload: JSONObject = {
        "covered_from": covered_from,
        "covered_to": covered_to,
        "markdown_body": markdown_body,
        "status": status.value,
        "source_refs": _MemoryCompactPayloadNormalizer.source_ref_payloads(source_refs),
    }
    if project is not None:
        payload["project"] = project
    return await client.post("/memory/compacts", payload)


async def alexandria_get_current_memory_compact(
    client: AlexandriaApiClient,
    project: str | None = None,
) -> JSONValue:
    """Read the current Memory Compact for a project.

    Args:
        client: Backend HTTP client.
        project: Optional project filter.

    Returns:
        Backend Memory Compact response.
    """
    query: JSONObject | None = None if project is None else {"project": project}
    return await client.get("/memory/compacts/current", params=query)


async def alexandria_get_memory_compact(
    client: AlexandriaApiClient,
    compact_id: str,
) -> JSONValue:
    """Read one selected Memory Compact by id.

    Args:
        client: Backend HTTP client.
        compact_id: Memory Compact identifier.

    Returns:
        Backend Memory Compact response.
    """
    return await client.get(f"/memory/compacts/{quote(compact_id, safe='')}")


async def alexandria_edit_memory_compact_draft(
    client: AlexandriaApiClient,
    compact_id: str,
    markdown_body: str,
    expected_draft_hash: str,
) -> JSONValue:
    """Edit only the last observed draft and invalidate its previous review.

    Args:
        client: Existing backend HTTP boundary.
        compact_id: Canonical draft identity.
        markdown_body: Final semantic body.
        expected_draft_hash: Prior draft snapshot fence.

    Returns:
        Fresh draft response requiring re-review before promotion.
    """
    return await client.post(
        f"/memory/compacts/{quote(compact_id, safe='')}/draft",
        {"markdown_body": markdown_body, "expected_draft_hash": expected_draft_hash},
    )


async def alexandria_review_memory_compact(
    client: AlexandriaApiClient,
    compact_id: str,
    source_observations: Sequence[Mapping[str, JSONValue]] | None = None,
) -> JSONValue:
    """Review one Memory Compact with the Memory Steward quality rubric.

    Args:
        client: Backend HTTP client.
        compact_id: Memory Compact identifier.
        source_observations: Optional current source observations.

    Returns:
        Backend Memory Compact review response.
    """
    payload: JSONObject = {
        "source_observations": _MemoryCompactPayloadNormalizer.source_observation_payloads(
            source_observations
        )
    }
    return await client.post(
        f"/memory/compacts/{quote(compact_id, safe='')}/review",
        payload,
    )


class _MemoryCompactPayloadNormalizer:
    """Normalize optional compact source reference and observation payloads."""

    @staticmethod
    def source_ref_payloads(
        source_refs: Sequence[Mapping[str, JSONValue]] | None,
    ) -> list[JSONObject]:
        """Normalize optional source reference mappings into JSON request payloads.

        Args:
            source_refs: Optional sequence of source reference mappings.

        Returns:
            Serialized source reference objects for the compact create payload.
        """
        if source_refs is None:
            return []
        payloads: list[JSONObject] = []
        for source_ref in source_refs:
            payload: JSONObject = {
                "source_type": source_ref["source_type"],
                "source_id": source_ref["source_id"],
                "title": source_ref["title"],
                "detail_path": source_ref["detail_path"],
            }
            source_hash = source_ref.get("source_hash")
            if source_hash is not None:
                payload["source_hash"] = source_hash
            payloads.append(payload)
        return payloads

    @staticmethod
    def source_observation_payloads(
        source_observations: Sequence[Mapping[str, JSONValue]] | None,
    ) -> list[JSONObject]:
        """Normalize optional source observation mappings into review request payloads.

        Args:
            source_observations: Optional sequence of current source hash observations.

        Returns:
            Serialized source observation objects for the compact review payload.
        """
        if source_observations is None:
            return []
        payloads: list[JSONObject] = []
        for observation in source_observations:
            payload: JSONObject = {
                "source_id": observation["source_id"],
            }
            detail_path = observation.get("detail_path")
            if detail_path is not None:
                payload["detail_path"] = detail_path
            current_source_hash = observation.get("current_source_hash")
            if current_source_hash is not None:
                payload["current_source_hash"] = current_source_hash
            payloads.append(payload)
        return payloads


async def alexandria_mark_memory_compact_current(
    client: AlexandriaApiClient,
    compact_id: str,
    expected_review_hash: str | None = None,
) -> JSONValue:
    """Promote one reviewed Memory Compact to CURRENT behind a receipt fence.

    Args:
        client: Backend HTTP client.
        compact_id: Memory Compact identifier.
        expected_review_hash: Reviewed-receipt hash admitted by a prior review.

    Returns:
        Backend Memory Compact response.
    """
    payload: JSONObject = (
        {}
        if expected_review_hash is None
        else {"expected_review_hash": expected_review_hash}
    )
    return await client.post(
        f"/memory/compacts/{quote(compact_id, safe='')}/mark-current",
        payload,
    )
