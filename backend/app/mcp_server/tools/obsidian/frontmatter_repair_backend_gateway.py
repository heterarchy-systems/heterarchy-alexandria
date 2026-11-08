"""MCP HTTP gateway for byte-preserving frontmatter repair."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.obsidian.interface.schemas.obsidian.notes.obsidian_source_schema import (
    ObsidianFrontmatterRepairRequest,
    ObsidianFrontmatterRepairResponse,
)
from app.shared.serialization.model_codec import schema_payload
from app.shared.type_validation.strict_json_value import model_validate_json_value


async def alexandria_repair_frontmatter(
    client: AlexandriaApiClient,
    request: ObsidianFrontmatterRepairRequest,
) -> ObsidianFrontmatterRepairResponse:
    """Repair one note's frontmatter while preserving durable body bytes.

    Args:
        client: Backend HTTP API client.
        request: Validated frontmatter repair request contract.

    Returns:
        Validated frontmatter repair response payload.
    """
    response = await client.post(
        "/obsidian/notes/repair-frontmatter",
        schema_payload(request, exclude_none=True),
    )
    return model_validate_json_value(ObsidianFrontmatterRepairResponse, response)
