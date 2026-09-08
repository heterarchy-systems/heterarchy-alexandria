"""heterarchy-alexandria MCP server bootstrap."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from app.mcp_server.backend_api_client import AlexandriaApiClient, AlexandriaApiSettings
from app.mcp_server.local_oauth.approval import register_local_oauth_approval_route
from app.mcp_server.local_oauth.runtime import LocalMcpOAuthRuntime
from app.mcp_server.tools.contexts.context_lifecycle_registration import (
    register_context_lifecycle_tools,
)
from app.mcp_server.tools.contexts.context_recall_registration import (
    register_context_recall_tools,
)
from app.mcp_server.tools.memory_compacts.memory_compact_registration import (
    register_memory_compact_tools,
)
from app.mcp_server.tools.memory_compacts.memory_steward_registration import (
    register_memory_steward_tools,
)
from app.mcp_server.tools.obsidian.obsidian_note_registration import (
    register_obsidian_note_tools,
)
from app.mcp_server.tools.obsidian.vault_maintenance_registration import (
    register_vault_maintenance_tools,
)
from app.mcp_server.tools.operations.maintenance_registration import (
    register_maintenance_tools,
)
from app.mcp_server.tools.operations.operations_registration import (
    register_operations_tools,
)
from app.mcp_server.tools.reconciliation.memory_reconciliation_registration import (
    register_memory_reconciliation_tools,
)
from app.mcp_server.type_validate.mcp_transport_enums import McpTransport

DEFAULT_MCP_TRANSPORT_HOST = "0.0.0.0"
DEFAULT_MCP_STREAMABLE_HTTP_PATH = "/mcp"
_LOCAL_TRANSPORT_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def build_mcp_server(
    client: AlexandriaApiClient | None = None,
    local_oauth_runtime: LocalMcpOAuthRuntime | None = None,
) -> MCPServer:
    """Build the heterarchy-alexandria MCPServer server.

    Args:
        client: Optional backend API client for tests.
        local_oauth_runtime: Optional self-hosted OAuth provider and settings.

    Returns:
        MCPServer server with async tool callbacks registered.
    """
    api_client = (
        AlexandriaApiClient(AlexandriaApiSettings.from_env())
        if client is None
        else client
    )
    instructions = (
        "Use these tools for Context Vault, Memory Steward operations, "
        "and Alexandria vault maintenance through the backend "
        "HTTP API. Do not hard delete unless "
        "a tool name explicitly says delete. Submit embedding reindex work "
        "through the maintenance queue and poll its job id. For incidents, "
        "inspect operational readiness and create a recovery plan before "
        "starting or retrying a recovery run."
    )
    if local_oauth_runtime is None:
        server = MCPServer(
            "heterarchy-alexandria",
            instructions=instructions,
        )
    else:
        server = MCPServer(
            "heterarchy-alexandria",
            instructions=instructions,
            auth_server_provider=local_oauth_runtime.provider,
            auth=local_oauth_runtime.auth_settings,
        )
        register_local_oauth_approval_route(
            server,
            local_oauth_runtime.provider,
        )
    register_memory_reconciliation_tools(server, api_client)
    register_context_recall_tools(server, api_client)
    register_memory_compact_tools(server, api_client)
    register_memory_steward_tools(server, api_client)
    register_context_lifecycle_tools(server, api_client)
    register_operations_tools(server, api_client)
    register_maintenance_tools(server, api_client)
    register_vault_maintenance_tools(server, api_client)
    register_obsidian_note_tools(server, api_client)
    return server


def mcp_transport_security(
    transport_host: str,
) -> TransportSecuritySettings | None:
    """Return the explicit MCP v2 DNS-rebinding policy for one bind host.

    Localhost keeps the SDK's secure default allowlist. A non-local bind is used
    behind Alexandria's outer FastAPI/OAuth boundary and therefore explicitly
    disables the SDK's localhost-only Host allowlist instead of relying on the
    implicit non-local behavior.

    Args:
        transport_host: Host address used by the Streamable HTTP or SSE transport.

    Returns:
        Explicit non-local transport security policy, or None for SDK defaults.
    """
    if transport_host in _LOCAL_TRANSPORT_HOSTS:
        return None
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def run_mcp_server(
    server: MCPServer,
    transport: McpTransport,
    transport_host: str = DEFAULT_MCP_TRANSPORT_HOST,
) -> None:
    """Run one MCP v2 server with transport-owned configuration.

    Args:
        server: Configured high-level MCP v2 server.
        transport: Selected transport protocol.
        transport_host: Bind host for network transports.
    """
    if transport is McpTransport.STDIO:
        server.run(transport="stdio")
        return
    security = mcp_transport_security(transport_host)
    if transport is McpTransport.SSE:
        server.run(
            transport="sse",
            host=transport_host,
            transport_security=security,
        )
        return
    server.run(
        transport="streamable-http",
        host=transport_host,
        streamable_http_path=DEFAULT_MCP_STREAMABLE_HTTP_PATH,
        json_response=True,
        transport_security=security,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the heterarchy-alexandria MCPServer server.

    Args:
        argv: Optional process arguments without the executable name.

    Returns:
        Process-style exit code after the MCP server exits normally.
    """
    parser = argparse.ArgumentParser(prog="heterarchy-alexandria mcp serve")
    parser.add_argument(
        "--transport",
        choices=[transport.value for transport in McpTransport],
        default=McpTransport.STDIO.value,
        help="MCP transport protocol.",
    )
    args = parser.parse_args(argv)
    server = build_mcp_server()
    run_mcp_server(
        server,
        McpTransport(args.transport),
        DEFAULT_MCP_TRANSPORT_HOST,
    )
    return 0
