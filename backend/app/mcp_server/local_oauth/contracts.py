"""Immutable persistence contracts for local MCP OAuth state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.mcp_server.local_oauth.local_oauth_enums import (
    LocalOAuthClientConnectionStatus,
    LocalOAuthTokenKind,
)
from app.shared.types.extra_types import JSONValue


@dataclass(frozen=True, slots=True)
class LocalMcpOAuthSettings:
    """Security and expiry policy for one local MCP authorization server."""

    issuer_url: str
    resource_url: str
    required_scopes: tuple[str, ...]
    default_scopes: tuple[str, ...]
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int
    authorization_code_ttl_seconds: int
    approval_ttl_seconds: int
    pairing_code_ttl_seconds: int
    max_approval_attempts: int
    approval_key: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class LocalOAuthPairingCode:
    """One-time local approval code returned only at creation time."""

    code: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class LocalOAuthClientRecord:
    """Persisted dynamic OAuth client registration."""

    client_id: str
    client_secret_ciphertext: str | None
    metadata: Mapping[str, JSONValue]
    issued_at: int
    secret_expires_at: int | None


@dataclass(frozen=True, slots=True)
class LocalOAuthAuthorizationRequestRecord:
    """Pending operator-approved OAuth authorization request."""

    request_id: str
    client_id: str
    client_name: str | None
    state: str | None
    scopes: tuple[str, ...]
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    resource: str
    expires_at: int
    approval_attempts: int
    consumed_at: int | None


@dataclass(frozen=True, slots=True)
class LocalOAuthAuthorizationCodeRecord:
    """One-time authorization code state loaded by its opaque raw value."""

    code: str
    client_id: str
    scopes: tuple[str, ...]
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    resource: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class LocalOAuthTokenRecord:
    """Active opaque OAuth token state loaded by its raw value."""

    token: str
    token_kind: LocalOAuthTokenKind
    family_id: str
    client_id: str
    scopes: tuple[str, ...]
    resource: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class LocalOAuthClientConnectionRecord:
    """Operator-visible MCP OAuth client state without credential material."""

    client_id: str
    client_name: str | None
    issued_at: int
    status: LocalOAuthClientConnectionStatus
    connected: bool
    scopes: tuple[str, ...]
    resource: str | None
    access_token_expires_at: int | None
    refresh_token_expires_at: int | None
    active_token_families: int
