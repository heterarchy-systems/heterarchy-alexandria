"""Feature-owned local oauth enums."""

from __future__ import annotations

from enum import StrEnum


class LocalOAuthTokenKind(StrEnum):
    """Persisted opaque token categories."""

    ACCESS = "access"
    REFRESH = "refresh"


class LocalOAuthClientConnectionStatus(StrEnum):
    """Public-safe lifecycle state for one registered MCP OAuth client."""

    REGISTERED = "registered"
    CONNECTED = "connected"
    EXPIRED = "expired"


class OAuthClientCredentialField(StrEnum):
    """SDK credential fields stored separately from extensible client metadata."""

    CLIENT_ID = "client_id"
    CLIENT_SECRET = "client_secret"
    CLIENT_ID_ISSUED_AT = "client_id_issued_at"
    CLIENT_SECRET_EXPIRES_AT = "client_secret_expires_at"
