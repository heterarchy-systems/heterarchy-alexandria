"""MCP transport and OAuth settings."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import ParseResult, urlparse

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.mcp_server.type_validate.oauth.config_contracts import McpApiConfig
from app.mcp_server.type_validate.oauth.mcp_auth_enums import (
    LocalOAuthHttpHost,
    McpAuthMode,
)
from app.shared.types.configuration_enums import SettingsModule
from app.shared.utils.config import settings_model_config

__all__ = ("McpApiConfig", "McpConfig")

_LOCAL_HTTP_HOSTS = frozenset(LocalOAuthHttpHost)


class McpConfig(BaseSettings):
    """Explicit MCP transport, OAuth and local approval settings."""

    model_config = settings_model_config(
        env_prefix="SERVICE_", module_name=SettingsModule.MCP
    ) | SettingsConfigDict(populate_by_name=True)

    mcp_transport_host: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="MCP transport host."),
    ]
    mcp_auth_mode: Annotated[McpAuthMode, Field(description="MCP auth mode.")]
    mcp_oauth_issuer: Annotated[str | None, Field(description="MCP OAuth issuer.")]
    mcp_oauth_audience: Annotated[str | None, Field(description="MCP OAuth audience.")]
    mcp_oauth_jwks_url: Annotated[str | None, Field(description="MCP OAuth JWKS URL.")]
    mcp_oauth_resource: Annotated[str | None, Field(description="MCP OAuth resource.")]
    mcp_oauth_authorization_servers: Annotated[
        str | None, Field(description="MCP OAuth authorization servers.")
    ]
    mcp_oauth_required_scope: Annotated[
        str, Field(description="MCP OAuth required scope.")
    ]
    mcp_local_approval_key: Annotated[
        SecretStr | None,
        Field(
            description="MCP local approval key.",
            validation_alias=AliasChoices(
                "SERVICE_MCP_LOCAL_APPROVAL_KEY", "ALEXANDRIA_OPERATOR_API_KEY"
            ),
            repr=False,
        ),
    ]
    mcp_local_access_token_ttl_seconds: Annotated[
        int,
        Field(
            description="MCP local access token TTL seconds.",
            ge=5 * 60,
            le=24 * 60 * 60,
        ),
    ]
    mcp_local_refresh_token_ttl_seconds: Annotated[
        int,
        Field(
            description="MCP local refresh token TTL seconds.",
            ge=24 * 60 * 60,
            le=365 * 24 * 60 * 60,
        ),
    ]
    mcp_local_authorization_code_ttl_seconds: Annotated[
        int,
        Field(
            description="MCP local authorization code TTL seconds.", ge=60, le=10 * 60
        ),
    ]
    mcp_local_approval_ttl_seconds: Annotated[
        int, Field(description="MCP local approval TTL seconds.", ge=60, le=30 * 60)
    ]
    mcp_local_pairing_code_ttl_seconds: Annotated[
        int,
        Field(description="MCP local pairing code TTL seconds.", ge=60, le=10 * 60),
    ]
    mcp_local_max_approval_attempts: Annotated[
        int, Field(description="MCP local maximum approval attempts.", ge=1, le=10)
    ]

    @field_validator(
        "mcp_oauth_issuer",
        "mcp_oauth_audience",
        "mcp_oauth_jwks_url",
        "mcp_oauth_resource",
        "mcp_oauth_authorization_servers",
        mode="before",
    )
    @classmethod
    def normalize_optional_oauth_text(cls, value: str | None) -> str | None:
        """Normalize optional OAuth text without enabling a mode implicitly.

        Args:
            value: Raw optional OAuth configuration string.

        Returns:
            Trimmed non-empty string, or None when blank or unset.
        """
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_mcp_oauth_configuration(self) -> McpConfig:
        """Fail closed when the selected MCP OAuth mode is incomplete.

        Returns:
            Validated MCP configuration instance.
        """
        if self.mcp_auth_mode is McpAuthMode.NONE:
            return self
        if self.mcp_auth_mode is McpAuthMode.OAUTH2:
            _require_values(
                "MCP OAuth mode",
                (
                    ("mcp_oauth_issuer", self.mcp_oauth_issuer),
                    ("mcp_oauth_audience", self.mcp_oauth_audience),
                    ("mcp_oauth_jwks_url", self.mcp_oauth_jwks_url),
                ),
            )
            return self
        _require_values(
            "MCP local OAuth mode",
            (
                ("mcp_oauth_issuer", self.mcp_oauth_issuer),
                ("mcp_oauth_resource", self.mcp_oauth_resource),
                ("mcp_local_approval_key", self.mcp_local_approval_key),
            ),
        )
        issuer = self.mcp_oauth_issuer or ""
        resource = self.mcp_oauth_resource or ""
        _validate_local_oauth_urls(issuer=issuer, resource=resource)
        if len(self.mcp_local_approval_key_value()) < 24:
            raise ValueError(
                "MCP local OAuth approval key must contain at least 24 characters"
            )
        return self

    def mcp_oauth_required_scopes(self) -> tuple[str, ...]:
        """Return normalized MCP OAuth scopes from configuration.

        Returns:
            Ordered tuple of required OAuth scope strings.
        """
        return tuple(scope for scope in self.mcp_oauth_required_scope.split() if scope)

    def mcp_local_oauth_default_scopes(self) -> tuple[str, ...]:
        """Return required scopes plus refresh-token connectivity scope.

        Returns:
            Ordered tuple of default local OAuth scope strings.
        """
        return tuple(
            dict.fromkeys((*self.mcp_oauth_required_scopes(), "offline_access"))
        )

    def mcp_local_approval_key_value(self) -> str:
        """Return the configured local approval credential after mode validation.

        Returns:
            Plaintext secret value for local OAuth operator approval.
        """
        if self.mcp_local_approval_key is None:
            raise RuntimeError("MCP local OAuth approval key is not configured")
        return self.mcp_local_approval_key.get_secret_value()

    def mcp_oauth_authorization_server_urls(self) -> tuple[str, ...]:
        """Return advertised OAuth authorization-server metadata URLs.

        Returns:
            Ordered tuple of authorization-server URLs.
        """
        if self.mcp_oauth_authorization_servers:
            return tuple(
                item.strip()
                for item in self.mcp_oauth_authorization_servers.split(",")
                if item.strip()
            )
        if self.mcp_oauth_issuer:
            return (self.mcp_oauth_issuer,)
        return ()


def _require_values(
    mode_name: str,
    values: tuple[tuple[str, str | SecretStr | None], ...],
) -> None:
    """Raise a useful validation error for required values in a selected mode.

    Args:
        mode_name: Human-readable OAuth mode label.
        values: Pairs of setting field name and configured value.
    """
    missing = [name for name, value in values if value is None or value == ""]
    if missing:
        raise ValueError(f"{mode_name} requires: {', '.join(missing)}")


def _validate_local_oauth_urls(issuer: str, resource: str) -> None:
    """Validate local OAuth origins and the MCP resource path.

    Args:
        issuer: Configured OAuth issuer URL.
        resource: Configured OAuth protected-resource URL.
    """
    issuer_url = urlparse(issuer)
    resource_url = urlparse(resource)
    _validate_oauth_url("mcp_oauth_issuer", issuer_url)
    _validate_oauth_url("mcp_oauth_resource", resource_url)
    if issuer_url.path not in {"", "/"}:
        raise ValueError("mcp_oauth_issuer must not include a path")
    if resource_url.path.rstrip("/") != "/mcp":
        raise ValueError("mcp_oauth_resource must end with /mcp")
    issuer_origin = (issuer_url.scheme, issuer_url.hostname, issuer_url.port)
    resource_origin = (resource_url.scheme, resource_url.hostname, resource_url.port)
    if issuer_origin != resource_origin:
        raise ValueError("MCP local OAuth issuer and resource must share one origin")


def _validate_oauth_url(name: str, parsed: ParseResult) -> None:
    """Validate a metadata URL against the MCP OAuth URL policy.

    Args:
        name: Setting field name for error reporting.
        parsed: Parsed URL components to validate.
    """
    scheme = parsed.scheme
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError(f"{name} must include a hostname")
    if scheme != "https" and not (scheme == "http" and hostname in _LOCAL_HTTP_HOSTS):
        raise ValueError(f"{name} must use HTTPS outside localhost")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{name} must not include userinfo")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not include query or fragment")
