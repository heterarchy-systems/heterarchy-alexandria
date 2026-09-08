"""MCP HTTP gateway for the high-level Obsidian relate operation."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.obsidian.interface.schemas.obsidian.obsidian_relation_schema import (
    ObsidianRelateRequestSchema,
    ObsidianRelateResponse,
)
from app.shared.serialization.model_codec import schema_payload
from app.shared.type_validation.strict_json_value import model_validate_json_value


async def alexandria_relate(
    client: AlexandriaApiClient,
    request: ObsidianRelateRequestSchema,
) -> ObsidianRelateResponse:
    """Persist one typed relation between two existing managed notes."""
    response = await client.post(
        "/obsidian/notes/relate",
        schema_payload(request, exclude_none=True),
    )
    return model_validate_json_value(ObsidianRelateResponse, response)
