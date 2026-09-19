"""Register versioned resume context package MCP tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.memory_compacts.memory_resume_package_tools import (
    alexandria_create_memory_resume_package,
    alexandria_get_memory_resume_package,
)
from app.shared.types.extra_types import JSONValue


def register_memory_resume_package_tools(
    server: MCPServer, api_client: AlexandriaApiClient
) -> None:
    """Register versioned worker-handoff resume package tools.

    The create tool seals a deduplicated, revision-incremented resume package
    as data; it issues no execution authority and binds no provider chat.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by callbacks.
    """

    @server.tool(name="alexandria_create_memory_resume_package")
    async def _tool_create_memory_resume_package(
        goal: str,
        summary: str,
        current_state: str,
        next_single_action: str,
        covered_from: str,
        covered_to: str,
        lineage_id: str,
        evidence_context_ids: Sequence[str],
        project: str | None = None,
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
        """Seal a versioned worker-handoff resume context package.

        Args:
            goal: Original objective sourced from the caller.
            summary: Single-line package summary.
            current_state: Single-line current-state statement.
            next_single_action: Single next action for the resuming worker.
            covered_from: Inclusive coverage start ISO timestamp.
            covered_to: Coverage end ISO timestamp.
            lineage_id: Stable lineage identity for the handoff chain.
            evidence_context_ids: Stored Context identifiers observed as
                evidence; hashes are computed server-side from stored content.
            project: Optional project scope recorded under Coverage.
            worker_id: Optional originating worker identity.
            run_id: Optional originating run identity.
            workspace_id: Optional workspace reference.
            session_id: Optional session reference.
            accepted_changes: Items with text and source_context_id keys.
            constraints: Items with text and source_context_id keys.
            verified_complete: Tasks verified complete by observed evidence.
            implemented_unverified: Tasks implemented but not verified.
            unfinished_tasks: Tasks intentionally left unfinished.
            uncertain_results: Results whose confidence is uncertain.
            blockers: Active blockers.
            request_id: Optional caller retry-fencing identity; retrying the
                same request id with different content is rejected.

        Returns:
            JSONValue result produced by tool create memory resume package.
        """
        return await alexandria_create_memory_resume_package(
            api_client,
            project=project,
            goal=goal,
            summary=summary,
            current_state=current_state,
            next_single_action=next_single_action,
            covered_from=covered_from,
            covered_to=covered_to,
            lineage_id=lineage_id,
            evidence_context_ids=evidence_context_ids,
            worker_id=worker_id,
            run_id=run_id,
            workspace_id=workspace_id,
            session_id=session_id,
            accepted_changes=accepted_changes,
            constraints=constraints,
            verified_complete=verified_complete,
            implemented_unverified=implemented_unverified,
            unfinished_tasks=unfinished_tasks,
            uncertain_results=uncertain_results,
            blockers=blockers,
            request_id=request_id,
        )

    @server.tool(name="alexandria_get_memory_resume_package")
    async def _tool_get_memory_resume_package(package_id: str) -> JSONValue:
        """Reopen one sealed resume context package as structured data.

        Args:
            package_id: Memory Compact identifier of the resume package.

        Returns:
            JSONValue result produced by tool get memory resume package.
        """
        return await alexandria_get_memory_resume_package(api_client, package_id)
