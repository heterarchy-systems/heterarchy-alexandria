"""Register agent-facing logical verified-upsert MCP tools."""

from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.obsidian.mutation_outcome_backend_gateway import (
    alexandria_get_mutation_outcome,
)
from app.mcp_server.tools.obsidian.verified_upsert_backend_gateway import (
    alexandria_verified_upsert,
    alexandria_verify,
)
from app.obsidian.interface.schemas.obsidian.obsidian_mutation_outcome_schema import (
    ObsidianMutationOutcomeRequestSchema,
    ObsidianMutationOutcomeResponseSchema,
)
from app.obsidian.interface.schemas.obsidian.obsidian_verified_upsert_schema import (
    ObsidianVerifiedUpsertRequestSchema,
    ObsidianVerifiedUpsertResponse,
    ObsidianVerifiedUpsertSelectorSchema,
    ObsidianVerifiedUpsertVerificationResponse,
)
from app.shared.type_validation.strict_json_arg import json_mode_arg


def register_verified_upsert_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register the high-level verified write and verify tools."""

    @server.tool(name="alexandria_verified_upsert")
    async def _tool_verified_upsert(
        request: Annotated[
            ObsidianVerifiedUpsertRequestSchema,
            json_mode_arg(ObsidianVerifiedUpsertRequestSchema),
        ],
    ) -> ObsidianVerifiedUpsertResponse:
        """Persist one logical note with readback and replay verification."""
        return await alexandria_verified_upsert(api_client, request)

    @server.tool(name="alexandria_get_mutation_outcome")
    async def _tool_get_mutation_outcome(
        request: ObsidianMutationOutcomeRequestSchema,
    ) -> ObsidianMutationOutcomeResponseSchema:
        """Resolve one fenced mutation outcome before any retry decision."""
        return await alexandria_get_mutation_outcome(api_client, request)

    @server.tool(name="alexandria_verify")
    async def _tool_verify(
        request: ObsidianVerifiedUpsertSelectorSchema,
    ) -> ObsidianVerifiedUpsertVerificationResponse:
        """Diagnose one logical or exact note through the canonical source."""
        return await alexandria_verify(api_client, request)
