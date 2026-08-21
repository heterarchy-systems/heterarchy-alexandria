"""Focused Skill Acquisition Agent MCP HTTP gateway functions."""

from __future__ import annotations

from app.librarian.domain.event_enum.skill_acquisition_enums import RiskLevel
from app.librarian.interface.schemas.librarian.skill_acquisition_schemas import (
    SkillAcquisitionJobRequest,
)
from app.librarian.interface.schemas.librarian.skill_search_schemas import (
    SkillCapabilitySearchRequest,
)
from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import (
    DEFAULT_SOURCE_AGENT,
    _items_or_empty,
    _path_segment,
)
from app.shared.serialization.model_codec import schema_payload
from app.shared.types.extra_types import JSONObject, JSONValue
from app.shared.utils.oauth_redaction import without_oauth_sensitive_fields


async def alexandria_search_skills(
    client: AlexandriaApiClient,
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
        client: Backend HTTP client.
        capability: Needed capability.
        task_goal: Current task goal.
        project: Optional project scope.
        environment: Runtime/framework context.
        required_tools: Tool names the skill must support.
        constraints: Operational or safety constraints.
        risk_tolerance: Maximum acceptable risk level.
        success_criteria: Criteria for sufficient reuse.
        limit: Maximum candidates.

    Returns:
        Search-first sufficiency decision.
    """
    request = SkillCapabilitySearchRequest(
        capability=capability,
        task_goal=task_goal,
        project=project,
        environment=environment,
        required_tools=_items_or_empty(required_tools),
        constraints=_items_or_empty(constraints),
        risk_tolerance=risk_tolerance,
        success_criteria=_items_or_empty(success_criteria),
        limit=max(1, min(limit, 10)),
    )
    payload = schema_payload(request, exclude_none=True)
    response = await client.post("/librarians/skill-library/search", payload)
    return without_oauth_sensitive_fields(response)


async def alexandria_start_skill_acquisition(
    client: AlexandriaApiClient,
    prompt: str,
    agent_name: str = DEFAULT_SOURCE_AGENT,
    project: str | None = None,
    task_summary: str | None = None,
    search_snapshot: JSONObject | None = None,
    acquisition_override_reason: str | None = None,
) -> JSONValue:
    """Start autonomous skill research, drafting, publication, and handoff.

    Provider/profile selection and credential handling are internal concerns and
    are intentionally not exposed to requesting agents.

    Args:
        client: Backend HTTP client.
        prompt: Missing-capability description.
        agent_name: Requesting agent name.
        project: Optional project scope.
        task_summary: Optional current task summary.
        search_snapshot: Optional search-first decision snapshot.
        acquisition_override_reason: Explicit reason for starting without search.

    Returns:
        Sanitized durable job response.
    """
    request = SkillAcquisitionJobRequest(
        prompt=prompt,
        agent_name=agent_name,
        project=project,
        task_summary=task_summary,
        search_snapshot=search_snapshot,
        acquisition_override_reason=acquisition_override_reason,
    )
    payload = schema_payload(request, exclude_none=True)
    response = await client.post("/librarians/skill-acquisition-jobs", payload)
    return without_oauth_sensitive_fields(response)


async def alexandria_skill_acquisition_job_status(
    client: AlexandriaApiClient,
    job_id: str,
) -> JSONValue:
    """Poll one autonomous skill-acquisition job.

    Args:
        client: Backend HTTP client.
        job_id: Skill-acquisition job identifier.

    Returns:
        Sanitized durable job response with result handles and handoff when ready.
    """
    response = await client.get(
        f"/librarians/skill-acquisition-jobs/{_path_segment(job_id)}"
    )
    return without_oauth_sensitive_fields(response)
