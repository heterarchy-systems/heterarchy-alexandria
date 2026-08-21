"""Runtime assembly for Alexandria's self-hosted MCP OAuth server."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from pydantic import AnyHttpUrl

from app.mcp_server.local_oauth.contracts import LocalMcpOAuthSettings
from app.mcp_server.local_oauth.provider import LocalMcpOAuthProvider
from app.mcp_server.local_oauth.repository import LocalMcpOAuthRepository
from app.mcp_server.type_validate.oauth.config_contracts import (
    LocalMcpOAuthRuntimeConfig,
)
from app.shared.infrastructure.database import Database
from app.shared.security.secret_cipher import SecretCipher


@dataclass(frozen=True, slots=True)
class LocalMcpOAuthRuntime:
    """Provider and FastMCP auth settings sharing one durable repository."""

    provider: LocalMcpOAuthProvider
    auth_settings: AuthSettings


def build_local_mcp_oauth_runtime(
    config: LocalMcpOAuthRuntimeConfig,
    database: Database,
    secret_cipher: SecretCipher,
) -> LocalMcpOAuthRuntime:
    """Build self-hosted OAuth runtime from validated application settings.

    Args:
        config: Validated application configuration in local OAuth mode.
        database: Lifecycle-owned database resource.
        secret_cipher: AES-GCM cipher for dynamic client secrets.

    Returns:
        Local OAuth provider and FastMCP settings.
    """
    issuer = config.mcp_oauth_issuer or ""
    resource = config.mcp_oauth_resource or ""
    approval_key = config.mcp_local_approval_key_value()
    required_scopes = config.mcp_oauth_required_scopes()
    default_scopes = config.mcp_local_oauth_default_scopes()
    provider = LocalMcpOAuthProvider(
        repository=LocalMcpOAuthRepository(database.session_factory()),
        secret_cipher=secret_cipher,
        settings=LocalMcpOAuthSettings(
            issuer_url=issuer,
            resource_url=resource,
            required_scopes=required_scopes,
            default_scopes=default_scopes,
            access_token_ttl_seconds=config.mcp_local_access_token_ttl_seconds,
            refresh_token_ttl_seconds=config.mcp_local_refresh_token_ttl_seconds,
            authorization_code_ttl_seconds=(
                config.mcp_local_authorization_code_ttl_seconds
            ),
            approval_ttl_seconds=config.mcp_local_approval_ttl_seconds,
            pairing_code_ttl_seconds=config.mcp_local_pairing_code_ttl_seconds,
            max_approval_attempts=config.mcp_local_max_approval_attempts,
            approval_key=approval_key,
        ),
    )
    auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl(issuer),
        resource_server_url=AnyHttpUrl(resource),
        required_scopes=list(required_scopes),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=list(default_scopes),
            default_scopes=list(default_scopes),
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    return LocalMcpOAuthRuntime(provider=provider, auth_settings=auth_settings)
