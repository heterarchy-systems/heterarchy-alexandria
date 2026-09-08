"""MCP gateway for the high-level memory recall endpoint."""

from __future__ import annotations

from pydantic import TypeAdapter

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.memory.interface.schemas.context.recall_schema import (
    RecallRequestSchema,
    RecallResponseSchema,
)
from app.shared.serialization.model_codec import schema_payload

_RESPONSE_ADAPTER = TypeAdapter(RecallResponseSchema)


async def alexandria_recall(
    client: AlexandriaApiClient,
    request: RecallRequestSchema,
) -> RecallResponseSchema:
    """Call high-level recall and preserve its typed provenance response."""
    payload = schema_payload(request, exclude_none=True)
    if payload.get("include_scopes") == []:
        payload.pop("include_scopes", None)
    if payload.get("related_projects") == []:
        payload.pop("related_projects", None)
    if payload.get("include_lifecycle_statuses") == []:
        payload.pop("include_lifecycle_statuses", None)
    response = await client.post("/memory/recall", payload)
    return _RESPONSE_ADAPTER.validate_python(response)
