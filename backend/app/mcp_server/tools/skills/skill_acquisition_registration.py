"""Register the focused Skill Acquisition Agent MCP surface."""

from __future__ import annotations

from mcp.server import MCPServer

from app.librarian.domain.event_enum.skill_acquisition_enums import RiskLevel
from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import DEFAULT_SOURCE_AGENT
from app.mcp_server.tools.skills.skill_backend_gateway import (
    alexandria_search_skills,
    alexandria_skill_acquisition_job_status,
    alexandria_start_skill_acquisition,
)
from app.shared.types.extra_types import JSONObject, JSONValue


def register_skill_acquisition_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register the minimal public Skill Acquisition Agent tools.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_search_skills")
    async def _tool_search_skills(
        capability: str,
        task_goal: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        required_tools: list[str] | None = None,
        constraints: list[str] | None = None,
        risk_tolerance: RiskLevel = RiskLevel.MEDIUM,
        success_criteria: list[str] | None = None,
        limit: int = 5,
    ) -> JSONValue:
        """Search reusable skill notes before starting acquisition.

        Args:
            capability: Capability used by this operation.
            task_goal: Task goal used by this operation.
            project: Project used by this operation.
            environment: Environment used by this operation.
            required_tools: Required tools used by this operation.
            constraints: Constraints used by this operation.
            risk_tolerance: Risk tolerance used by this operation.
            success_criteria: Success criteria used by this operation.
            limit: Maximum number of items to process or return.

        Returns:
            JSONValue result produced by tool search skills.
        """
        return await alexandria_search_skills(
            api_client,
            capability=capability,
            task_goal=task_goal,
            project=project,
            environment=environment,
            required_tools=required_tools,
            constraints=constraints,
            risk_tolerance=risk_tolerance,
            success_criteria=success_criteria,
            limit=limit,
        )

    @server.tool(name="alexandria_start_skill_acquisition")
    async def _tool_start_skill_acquisition(
        prompt: str,
        agent_name: str = DEFAULT_SOURCE_AGENT,
        project: str | None = None,
        task_summary: str | None = None,
        search_snapshot: JSONObject | None = None,
        acquisition_override_reason: str | None = None,
    ) -> JSONValue:
        """Start autonomous research, drafting, publication, and handoff for a missing skill.

        Args:
            prompt: Prompt used by this operation.
            agent_name: Agent name used by this operation.
            project: Project used by this operation.
            task_summary: Task summary used by this operation.
            search_snapshot: Search snapshot used by this operation.
            acquisition_override_reason: Acquisition override reason used by this operation.

        Returns:
            JSONValue result produced by tool start skill acquisition.
        """
        return await alexandria_start_skill_acquisition(
            api_client,
            prompt=prompt,
            agent_name=agent_name,
            project=project,
            task_summary=task_summary,
            search_snapshot=search_snapshot,
            acquisition_override_reason=acquisition_override_reason,
        )

    @server.tool(name="alexandria_skill_acquisition_job_status")
    async def _tool_skill_acquisition_job_status(job_id: str) -> JSONValue:
        """Poll one autonomous skill-acquisition job and return its handoff when ready.

        Args:
            job_id: Identifier for job.

        Returns:
            JSONValue result produced by tool skill acquisition job status.
        """
        return await alexandria_skill_acquisition_job_status(api_client, job_id)
