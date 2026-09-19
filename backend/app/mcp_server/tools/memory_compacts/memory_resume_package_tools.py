"""MCP HTTP tool adapters for versioned resume context packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import quote

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.memory.interface.schemas.memory_compact.memory_resume_package_schema import (
    MemoryResumePackageCreateRequest,
)
from app.shared.type_validation.strict_json_value import model_validate_json_value
from app.shared.types.extra_types import JSONObject, JSONValue


async def alexandria_create_memory_resume_package(
    client: AlexandriaApiClient,
    *,
    project: str | None,
    goal: str,
    summary: str,
    current_state: str,
    next_single_action: str,
    covered_from: str,
    covered_to: str,
    lineage_id: str,
    evidence_context_ids: Sequence[str],
    worker_id: str | None = None,
    run_id: str | None = None,
    workspace_id: str | None = None,
    session_id: str | None = None,
    accepted_changes: Sequence[Mapping[str, JSONValue]] | None = None,
    constraints: Sequence[Mapping[str, JSONValue]] | None = None,
    verified_complete: Sequence[str] = (),
    implemented_unverified: Sequence[str] = (),
    unfinished_tasks: Sequence[str] = (),
    uncertain_results: Sequence[str] = (),
    blockers: Sequence[str] = (),
    request_id: str | None = None,
) -> JSONValue:
    """Seal one versioned resume context package through the backend API.

    Args:
        client: Backend HTTP client.
        project: Optional project scope recorded under Coverage.
        goal: Original objective sourced from the caller.
        summary: Single-line package summary.
        current_state: Single-line current-state statement.
        next_single_action: Single next action for the resuming worker.
        covered_from: Inclusive coverage start ISO timestamp.
        covered_to: Coverage end ISO timestamp.
        lineage_id: Stable lineage identity for the handoff chain.
        evidence_context_ids: Stored Context identifiers observed as evidence.
        worker_id: Optional originating worker identity.
        run_id: Optional originating run identity.
        workspace_id: Optional workspace reference.
        session_id: Optional session reference.
        accepted_changes: Attributed accepted changes keyed by text and
            source_context_id.
        constraints: Attributed constraints keyed by text and
            source_context_id.
        verified_complete: Tasks verified complete by observed evidence.
        implemented_unverified: Tasks implemented but not verified.
        unfinished_tasks: Tasks intentionally left unfinished.
        uncertain_results: Results whose confidence is uncertain.
        blockers: Active blockers.
        request_id: Optional caller retry-fencing identity.

    Returns:
        Backend resume package response payload.
    """
    payload: JSONObject = {
        "project": project,
        "goal": goal,
        "summary": summary,
        "current_state": current_state,
        "next_single_action": next_single_action,
        "covered_from": covered_from,
        "covered_to": covered_to,
        "lineage": {
            "lineage_id": lineage_id,
            "worker_id": worker_id,
            "run_id": run_id,
            "workspace_id": workspace_id,
            "session_id": session_id,
        },
        "evidence_context_ids": list(evidence_context_ids),
        "accepted_changes": [dict(item) for item in accepted_changes or ()],
        "constraints": [dict(item) for item in constraints or ()],
        "verified_complete": list(verified_complete),
        "implemented_unverified": list(implemented_unverified),
        "unfinished_tasks": list(unfinished_tasks),
        "uncertain_results": list(uncertain_results),
        "blockers": list(blockers),
        "request_id": request_id,
    }
    request = model_validate_json_value(MemoryResumePackageCreateRequest, payload)
    return await client.post(
        "/memory/resume-packages",
        request.model_dump(mode="json"),
    )


async def alexandria_get_memory_resume_package(
    client: AlexandriaApiClient,
    package_id: str,
) -> JSONValue:
    """Reopen one sealed resume package through the backend API.

    Args:
        client: Backend HTTP client.
        package_id: Memory Compact identifier of the resume package.

    Returns:
        Backend structured resume package response payload.
    """
    return await client.get(f"/memory/resume-packages/{quote(package_id, safe='')}")
