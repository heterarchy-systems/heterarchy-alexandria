"""MCP HTTP gateway for high-level logical verified upsert."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.obsidian.interface.schemas.obsidian.obsidian_verified_upsert_schema import (
    ObsidianVerifiedUpsertRequestSchema,
    ObsidianVerifiedUpsertResponse,
    ObsidianVerifiedUpsertSelectorSchema,
    ObsidianVerifiedUpsertVerificationResponse,
)
from app.shared.serialization.model_codec import schema_payload
from app.shared.type_validation.strict_json_value import model_validate_json_value


async def alexandria_verified_upsert(
    client: AlexandriaApiClient,
    request: ObsidianVerifiedUpsertRequestSchema,
) -> ObsidianVerifiedUpsertResponse:
    """Resolve and persist one logical note through the verified write API."""
    response = await client.post(
        "/obsidian/verified-upsert",
        schema_payload(request, exclude_none=True),
    )
    return model_validate_json_value(ObsidianVerifiedUpsertResponse, response)


async def alexandria_verify(
    client: AlexandriaApiClient,
    request: ObsidianVerifiedUpsertSelectorSchema,
) -> ObsidianVerifiedUpsertVerificationResponse:
    """Run one source/index/duplicate verification composite."""
    response = await client.post(
        "/obsidian/verified-upsert/verify",
        schema_payload(request, exclude_none=True),
    )
    return model_validate_json_value(
        ObsidianVerifiedUpsertVerificationResponse,
        response,
    )
