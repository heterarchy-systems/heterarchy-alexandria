"""MCP gateway for the high-level managed-spec execution contract."""

from __future__ import annotations

from pydantic import TypeAdapter

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.obsidian.interface.schemas.managed_spec.managed_spec_schema import (
    ManagedSpecRequestSchema,
    ManagedSpecResponseSchema,
)
from app.shared.serialization.model_codec import schema_payload
from app.shared.serialization.orjson_codec import dumps_json

_RESPONSE_ADAPTER = TypeAdapter(ManagedSpecResponseSchema)


async def alexandria_execute_managed_spec(
    client: AlexandriaApiClient,
    request: ManagedSpecRequestSchema,
) -> ManagedSpecResponseSchema:
    """Send one validated prepare/complete request to the backend."""
    response = await client.post(
        "/obsidian/managed-specs/execute",
        schema_payload(request, exclude_none=True),
    )
    return _RESPONSE_ADAPTER.validate_json(dumps_json(response))
