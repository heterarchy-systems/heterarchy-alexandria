"""Structural configuration contracts owned by the MCP boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode


# protocol-contract: structural-seam
class McpHttpAuthConfig(Protocol):
    """Configuration surface required by the public MCP bearer-token gate."""

    mcp_auth_mode: McpAuthMode
    mcp_oauth_issuer: str | None
    mcp_oauth_audience: str | None
    mcp_oauth_jwks_url: str | None

    def mcp_oauth_required_scopes(self) -> tuple[str, ...]:
        """Return normalized scopes required by the MCP resource.

        Returns:
            Ordered scopes enforced by the protected resource.
        """
        ...


# protocol-contract: structural-seam
class McpProtectedResourceConfig(Protocol):
    """Configuration surface required by protected-resource discovery."""

    mcp_oauth_resource: str | None

    def mcp_oauth_required_scopes(self) -> tuple[str, ...]:
        """Return normalized scopes required by the MCP resource.

        Returns:
            Ordered scopes enforced by the protected resource.
        """
        ...

    def mcp_oauth_authorization_server_urls(self) -> tuple[str, ...]:
        """Return authorization-server URLs advertised by the MCP resource.

        Returns:
            Canonical authorization-server discovery URLs.
        """
        ...


# protocol-contract: structural-seam
class LocalMcpOAuthRuntimeConfig(Protocol):
    """Configuration surface required to assemble self-hosted MCP OAuth."""

    mcp_oauth_issuer: str | None
    mcp_oauth_resource: str | None
    mcp_local_access_token_ttl_seconds: int
    mcp_local_refresh_token_ttl_seconds: int
    mcp_local_authorization_code_ttl_seconds: int
    mcp_local_approval_ttl_seconds: int
    mcp_local_pairing_code_ttl_seconds: int
    mcp_local_max_approval_attempts: int

    def mcp_local_approval_key_value(self) -> str:
        """Return the validated local approval credential.

        Returns:
            Secret bootstrap credential for local operator approval.
        """
        ...

    def mcp_oauth_required_scopes(self) -> tuple[str, ...]:
        """Return normalized scopes required by the MCP resource.

        Returns:
            Ordered scopes enforced by the protected resource.
        """
        ...

    def mcp_local_oauth_default_scopes(self) -> tuple[str, ...]:
        """Return default scopes granted by the local authorization server.

        Returns:
            Ordered default scopes for dynamic local clients.
        """
        ...


@dataclass(slots=True)
class DefaultMcpProtectedResourceConfig:
    """Safe metadata fallback used before application state is initialized."""

    mcp_oauth_resource: str | None = None

    def mcp_oauth_required_scopes(self) -> tuple[str, ...]:
        """Return the repository default protected-resource scope.

        Returns:
            Minimal scope exposed before application state is initialized.
        """
        return ("alexandria:mcp",)

    def mcp_oauth_authorization_server_urls(self) -> tuple[str, ...]:
        """Return no authorization server when runtime config is unavailable.

        Returns:
            Empty discovery URL collection for the safe fallback state.
        """
        return ()
