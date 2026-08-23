"""Routes for MCP OAuth protected-resource metadata discovery."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request

from app.mcp_server.protected_resource_metadata import protected_resource_metadata
from app.mcp_server.type_validate.oauth.auth_contracts import (
    MCP_OAUTH_PROTECTED_RESOURCE_PATH,
)
from app.mcp_server.type_validate.oauth.config_contracts import (
    DefaultMcpProtectedResourceConfig,
    McpProtectedResourceConfig,
)
from app.shared.types.extra_types import JSONObject

router = APIRouter(tags=["mcp-oauth"])


@router.get(MCP_OAUTH_PROTECTED_RESOURCE_PATH, response_model=None)
def read_mcp_protected_resource_metadata(request: Request) -> JSONObject:
    """Return OAuth protected-resource metadata for ChatGPT MCP clients.

    Args:
        request: Incoming request used to infer the public resource origin.

    Returns:
        OAuth protected-resource metadata payload.
    """
    try:
        config = cast(McpProtectedResourceConfig, request.app.state.app_config)
    except AttributeError:
        config = DefaultMcpProtectedResourceConfig()
    return protected_resource_metadata(request, config)
