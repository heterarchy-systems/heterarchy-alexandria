"""Structural configuration contracts owned by the MCP boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.shared.types.configuration_enums import SettingsModule
from app.shared.utils.config import settings_model_config


class McpApiConfig(BaseSettings):
    """Environment-backed settings for the MCP HTTP client."""

    model_config = settings_model_config(
        env_prefix="", module_name=SettingsModule.MCP
    ) | SettingsConfigDict(populate_by_name=True)

    base_url: Annotated[
        str,
        Field(
            description="Base URL for the Alexandria API.",
            validation_alias=AliasChoices("ALEXANDRIA_API_URL", "HERMES_API_URL"),
        ),
    ]
    timeout: Annotated[
        float,
        Field(
            description="Timeout for the Alexandria API.",
            validation_alias="ALEXANDRIA_API_TIMEOUT_SECONDS",
        ),
    ]

    @classmethod
    def from_env(cls) -> McpApiConfig:
        """Create settings through the typed MCP settings boundary.

        Returns:
            Environment-backed MCP API client configuration.
        """
        return cls()

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        """Normalize the explicitly configured backend URL.

        Args:
            value: Raw backend URL string.

        Returns:
            Trimmed backend URL without a trailing slash.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("Alexandria API base URL must not be blank")
        return stripped.rstrip("/")

    @field_validator("timeout")
    @classmethod
    def normalize_timeout(cls, value: float) -> float:
        """Clamp configured timeout to at least one second.

        Args:
            value: Raw timeout value in seconds.

        Returns:
            Bounded timeout value in seconds.
        """
        return max(1.0, value)


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

    mcp_oauth_resource: str | None

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
