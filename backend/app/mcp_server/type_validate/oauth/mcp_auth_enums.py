"""Feature-owned mcp auth enums."""

from __future__ import annotations

from enum import StrEnum


class McpAuthMode(StrEnum):
    """Supported authentication modes for the public MCP endpoint."""

    NONE = "none"
    OAUTH2 = "oauth2"
    LOCAL_OAUTH2 = "local_oauth2"


class JwtAlgorithm(StrEnum):
    """JWT algorithms accepted by the MCP OAuth resource server."""

    RS256 = "RS256"


class OAuthBearerErrorCode(StrEnum):
    """OAuth bearer challenge error codes used at the MCP boundary."""

    INVALID_REQUEST = "invalid_request"
    INVALID_TOKEN = "invalid_token"
    INSUFFICIENT_SCOPE = "insufficient_scope"
