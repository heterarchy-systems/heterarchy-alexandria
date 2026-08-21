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
