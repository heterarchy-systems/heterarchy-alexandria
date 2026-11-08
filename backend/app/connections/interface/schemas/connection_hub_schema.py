"""Public connection-hub configuration schema."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.mcp_server.local_oauth.local_oauth_enums import (
    LocalOAuthClientConnectionStatus,
)
from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.schemas.datetime_schemas import AwareTimestamp


class ConnectionHubStatusResponse(StrictSchemaModel):
    """Safe runtime details needed by the browser connection page."""

    app_env: Annotated[
        str, Field(description="App env for this connection hub status response.")
    ]
    mcp_auth_mode: Annotated[
        McpAuthMode,
        Field(description="MCP auth mode for this connection hub status response."),
    ]
    mcp_endpoint: Annotated[
        str, Field(description="MCP endpoint for this connection hub status response.")
    ]
    mcp_oauth_enabled: Annotated[
        bool,
        Field(description="MCP OAuth enabled for this connection hub status response."),
    ]
    mcp_oauth_issuer: Annotated[
        str | None,
        Field(description="MCP OAuth issuer for this connection hub status response."),
    ]
    local_only: Annotated[
        bool, Field(description="Local only for this connection hub status response.")
    ]


class McpPairingCodeResponse(StrictSchemaModel):
    """Single-use MCP approval code shown once to the local operator."""

    code: Annotated[str, Field(description="Code for this MCP pairing code response.")]
    expires_at: Annotated[
        AwareTimestamp,
        Field(description="Expires at for this MCP pairing code response."),
    ]


class McpOAuthClientConnectionResponse(StrictSchemaModel):
    """Operator-visible MCP OAuth client connection state."""

    client_id: Annotated[
        str,
        Field(
            description="Client identifier for this MCP o auth client connection response."
        ),
    ]
    client_name: Annotated[
        str | None,
        Field(
            description="Client name for this MCP o auth client connection response."
        ),
    ]
    status: Annotated[
        LocalOAuthClientConnectionStatus,
        Field(description="Status for this MCP o auth client connection response."),
    ]
    connected: Annotated[
        bool,
        Field(description="Connected for this MCP o auth client connection response."),
    ]
    scopes: Annotated[
        list[str],
        Field(description="Scopes for this MCP o auth client connection response."),
    ]
    resource: Annotated[
        str | None,
        Field(description="Resource for this MCP o auth client connection response."),
    ]
    issued_at: Annotated[
        AwareTimestamp,
        Field(description="Issued at for this MCP o auth client connection response."),
    ]
    access_token_expires_at: Annotated[
        AwareTimestamp | None,
        Field(
            description="Access token expires at for this MCP o auth client connection response."
        ),
    ]
    refresh_token_expires_at: Annotated[
        AwareTimestamp | None,
        Field(
            description="Refresh token expires at for this MCP o auth client connection response."
        ),
    ]
    active_token_families: Annotated[
        int,
        Field(
            description="Active token families for this MCP o auth client connection response."
        ),
    ]
    supports_disconnect: Annotated[
        bool,
        Field(
            description="Supports disconnect for this MCP o auth client connection response."
        ),
    ]
    supports_extension: Annotated[
        bool,
        Field(
            description="Supports extension for this MCP o auth client connection response."
        ),
    ]


class McpOAuthClientConnectionListResponse(StrictSchemaModel):
    """List response for MCP OAuth clients registered with this endpoint."""

    clients: Annotated[
        list[McpOAuthClientConnectionResponse],
        Field(
            description="Clients for this MCP o auth client connection list response."
        ),
    ]
    extension_policy: Annotated[
        str,
        Field(
            description="Extension policy for this MCP o auth client connection list response."
        ),
    ]
