"""Factory for MCP HTTP authentication gate wiring."""

from __future__ import annotations

from app.mcp_server.http_auth_gate import McpHttpAuthGate
from app.mcp_server.oauth_bearer_verifier import (
    OAuthBearerTokenVerifier,
    OAuthBearerVerifierConfig,
)
from app.mcp_server.type_validate.oauth.config_contracts import McpHttpAuthConfig
from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode


def build_mcp_http_auth_gate(config: McpHttpAuthConfig) -> McpHttpAuthGate:
    """Build the public MCP HTTP auth gate from application config.

    Args:
        config: Application configuration.

    Returns:
        Configured MCP HTTP authentication gate.
    """
    if config.mcp_auth_mode != McpAuthMode.OAUTH2:
        return McpHttpAuthGate(McpAuthMode.NONE)
    verifier_config = OAuthBearerVerifierConfig(
        issuer=config.mcp_oauth_issuer or "",
        audience=config.mcp_oauth_audience or "",
        jwks_url=config.mcp_oauth_jwks_url or "",
        required_scopes=config.mcp_oauth_required_scopes(),
    )
    return McpHttpAuthGate(
        McpAuthMode.OAUTH2,
        OAuthBearerTokenVerifier(verifier_config),
    )
