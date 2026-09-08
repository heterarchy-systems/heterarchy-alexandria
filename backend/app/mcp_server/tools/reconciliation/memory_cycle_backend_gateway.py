"""MCP HTTP gateway for the high-level memory-cycle operation."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.memory.interface.schemas.reconciliation.cycles.memory_cycle_schema import (
    MemoryCycleRequestSchema,
    MemoryCycleResponseSchema,
)
from app.shared.serialization.model_codec import schema_payload
from app.shared.type_validation.strict_json_value import model_validate_json_value


async def alexandria_memory_cycle(
    client: AlexandriaApiClient,
    request: MemoryCycleRequestSchema,
) -> MemoryCycleResponseSchema:
    """Preview or apply one bounded typed memory cycle through HTTP."""
    response = await client.post(
        "/memory/cycle",
        schema_payload(request, exclude_none=True),
    )
    return model_validate_json_value(MemoryCycleResponseSchema, response)
