"""MCP gateway for the high-level memory recall endpoint."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.memory.interface.schemas.context.recall_request_schema import (
    RecallRequestSchema,
)
from app.memory.interface.schemas.context.recall_response_schema import (
    RecallResponseSchema,
)
from app.shared.serialization.model_codec import schema_payload
from app.shared.type_validation.strict_json_value import model_validate_json_value


async def alexandria_recall(
    client: AlexandriaApiClient,
    request: RecallRequestSchema,
) -> RecallResponseSchema:
    """Call high-level recall and preserve its typed provenance response.

    Args:
        client: Backend HTTP API client.
        request: Validated high-level recall request contract.

    Returns:
        Validated high-level recall response payload.
    """
    payload = schema_payload(request, exclude_none=True)
    if payload.get("include_scopes") == []:
        payload.pop("include_scopes", None)
    if payload.get("related_projects") == []:
        payload.pop("related_projects", None)
    if payload.get("include_lifecycle_statuses") == []:
        payload.pop("include_lifecycle_statuses", None)
    response = await client.post("/memory/recall", payload)
    return model_validate_json_value(RecallResponseSchema, response)
