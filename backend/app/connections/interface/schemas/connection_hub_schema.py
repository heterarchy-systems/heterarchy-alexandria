"""Public connection-hub configuration schema."""

from __future__ import annotations

from typing import Annotated

from app.mcp_server.local_oauth.local_oauth_enums import (
    LocalOAuthClientConnectionStatus,
)
from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp


class ConnectionHubStatusResponse(StrictSchemaModel):
    """Safe runtime details needed by the browser connection page."""

    app_env: Annotated[
        str, described_field("App env for this connection hub status response.")
    ]
    mcp_auth_mode: Annotated[
        McpAuthMode,
        described_field("MCP auth mode for this connection hub status response."),
    ]
    mcp_endpoint: Annotated[
        str, described_field("MCP endpoint for this connection hub status response.")
    ]
    mcp_oauth_enabled: Annotated[
        bool,
        described_field("MCP OAuth enabled for this connection hub status response."),
    ]
    mcp_oauth_issuer: Annotated[
        str | None,
        described_field("MCP OAuth issuer for this connection hub status response."),
    ]
    local_only: Annotated[
        bool, described_field("Local only for this connection hub status response.")
    ]


class McpPairingCodeResponse(StrictSchemaModel):
    """Single-use MCP approval code shown once to the local operator."""

    code: Annotated[str, described_field("Code for this MCP pairing code response.")]
    expires_at: Annotated[
        AwareTimestamp,
        described_field("Expires at for this MCP pairing code response."),
    ]


class McpOAuthClientConnectionResponse(StrictSchemaModel):
    """Operator-visible MCP OAuth client connection state."""

    client_id: Annotated[
        str,
        described_field(
            "Client identifier for this MCP o auth client connection response."
        ),
    ]
    client_name: Annotated[
        str | None,
        described_field("Client name for this MCP o auth client connection response."),
    ]
    status: Annotated[
        LocalOAuthClientConnectionStatus,
        described_field("Status for this MCP o auth client connection response."),
    ]
    connected: Annotated[
        bool,
        described_field("Connected for this MCP o auth client connection response."),
    ]
    scopes: Annotated[
        list[str],
        described_field("Scopes for this MCP o auth client connection response."),
    ]
    resource: Annotated[
        str | None,
        described_field("Resource for this MCP o auth client connection response."),
    ]
    issued_at: Annotated[
        AwareTimestamp,
        described_field("Issued at for this MCP o auth client connection response."),
    ]
    access_token_expires_at: Annotated[
        AwareTimestamp | None,
        described_field(
            "Access token expires at for this MCP o auth client connection response."
        ),
    ]
    refresh_token_expires_at: Annotated[
        AwareTimestamp | None,
        described_field(
            "Refresh token expires at for this MCP o auth client connection response."
        ),
    ]
    active_token_families: Annotated[
        int,
        described_field(
            "Active token families for this MCP o auth client connection response."
        ),
    ]
    supports_disconnect: Annotated[
        bool,
        described_field(
            "Supports disconnect for this MCP o auth client connection response."
        ),
    ]
    supports_extension: Annotated[
        bool,
        described_field(
            "Supports extension for this MCP o auth client connection response."
        ),
    ]


class McpOAuthClientConnectionListResponse(StrictSchemaModel):
    """List response for MCP OAuth clients registered with this endpoint."""

    clients: Annotated[
        list[McpOAuthClientConnectionResponse],
        described_field("Clients for this MCP o auth client connection list response."),
    ]
    extension_policy: Annotated[
        str,
        described_field(
            "Extension policy for this MCP o auth client connection list response."
        ),
    ]
