"""MCP HTTP gateway for the durable mutation outcome query."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.obsidian.interface.schemas.obsidian.obsidian_mutation_outcome_schema import (
    ObsidianMutationOutcomeRequestSchema,
    ObsidianMutationOutcomeResponseSchema,
)
from app.shared.serialization.model_codec import schema_payload
from app.shared.type_validation.strict_json_value import model_validate_json_value


async def alexandria_get_mutation_outcome(
    client: AlexandriaApiClient,
    request: ObsidianMutationOutcomeRequestSchema,
) -> ObsidianMutationOutcomeResponseSchema:
    """Resolve one mutation outcome before any retry decision.

    Args:
        client: Backend HTTP API client.
        request: Validated mutation outcome lookup request contract.

    Returns:
        Validated mutation outcome response payload.
    """
    response = await client.post(
        "/obsidian/mutations/outcome",
        schema_payload(request, exclude_none=True),
    )
    return model_validate_json_value(ObsidianMutationOutcomeResponseSchema, response)
