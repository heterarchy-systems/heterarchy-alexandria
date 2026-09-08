"""Common service configuration model.

This module reads shared service configuration from ``.env`` and environment
variables. Most service fields use the ``SERVICE_`` prefix.
"""

from __future__ import annotations

from urllib.parse import ParseResult, urlparse

from pydantic import (
    SecretStr,
    field_validator,
    model_validator,
)

from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.platform.config.app_config_fields import (
    _LOCAL_HTTP_HOSTS,
    AppConfigFields,
)


class AppConfig(AppConfigFields):
    """Common service settings model.

    Role:
        Centralizes global service settings such as app name, environment, version,
        and log level. The public method count exceeds the normal review threshold
        because Pydantic validators and normalized configuration projections must
        remain attached to the single external settings boundary.
    """

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
            value: Value supplied to normalize_optional_oauth_text.
        Returns:
            str | None: Value produced by normalize_optional_oauth_text."""
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("memory_reconciliation_provider_id")
    @classmethod
    def normalize_memory_reconciliation_provider_id(
        cls,
        value: str | None,
    ) -> str | None:
        """Normalize the optional provider id without enabling one implicitly.

        Args:
            value: Value supplied to normalize_memory_reconciliation_provider_id.
        Returns:
            str | None: Value produced by normalize_memory_reconciliation_provider_id."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("memory_reconciliation_model")
    @classmethod
    def normalize_memory_reconciliation_model(cls, value: str) -> str:
        """Normalize the configured fallback model name.

        Args:
            value: Value supplied to normalize_memory_reconciliation_model.
        Returns:
            str: Value produced by normalize_memory_reconciliation_model."""
        return value.strip()

    @model_validator(mode="after")
    def validate_mcp_oauth_configuration(self) -> AppConfig:
        """Fail closed when the selected MCP OAuth mode is incomplete.

        Returns:
            AppConfig: Value produced by validate_mcp_oauth_configuration."""
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
        approval_key = self.mcp_local_approval_key_value()
        if len(approval_key) < 24:
            raise ValueError(
                "MCP local OAuth approval key must contain at least 24 characters"
            )
        return self

    def mcp_oauth_required_scopes(self) -> tuple[str, ...]:
        """Return normalized MCP OAuth scopes from configuration.

        Returns:
            tuple[str, ...]: Value produced by mcp_oauth_required_scopes."""
        return tuple(scope for scope in self.mcp_oauth_required_scope.split() if scope)

    def mcp_local_oauth_default_scopes(self) -> tuple[str, ...]:
        """Return required scopes plus refresh-token connectivity scope.

        Returns:
            tuple[str, ...]: Value produced by mcp_local_oauth_default_scopes."""
        return tuple(
            dict.fromkeys((*self.mcp_oauth_required_scopes(), "offline_access"))
        )

    def mcp_local_approval_key_value(self) -> str:
        """Return the configured local approval credential after mode validation.

        Returns:
            str: Value produced by mcp_local_approval_key_value."""
        if self.mcp_local_approval_key is None:
            raise RuntimeError("MCP local OAuth approval key is not configured")
        return self.mcp_local_approval_key.get_secret_value()

    def mcp_oauth_authorization_server_urls(self) -> tuple[str, ...]:
        """Return advertised OAuth authorization-server metadata URLs.

        Returns:
            tuple[str, ...]: Value produced by mcp_oauth_authorization_server_urls."""
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
    """Execute require values.

    Args:
        mode_name: Mode name used by this operation.
        values: Values being processed.
    """
    missing = [name for name, value in values if value is None or value == ""]
    if missing:
        raise ValueError(f"{mode_name} requires: {', '.join(missing)}")


def _validate_local_oauth_urls(issuer: str, resource: str) -> None:
    """Validate local oauth urls.

    Args:
        issuer: Issuer used by this operation.
        resource: Resource used by this operation.
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
    """Validate oauth url.

    Args:
        name: Name used by this operation.
        parsed: Parsed used by this operation.
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
