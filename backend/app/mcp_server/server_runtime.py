"""heterarchy-alexandria MCP server bootstrap."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from mcp.server.fastmcp import FastMCP

from app.mcp_server.backend_api_client import AlexandriaApiClient, AlexandriaApiSettings
from app.mcp_server.local_oauth.approval import register_local_oauth_approval_route
from app.mcp_server.local_oauth.runtime import LocalMcpOAuthRuntime
from app.mcp_server.tools.context_lifecycle_registration import (
    register_context_lifecycle_tools,
)
from app.mcp_server.tools.context_recall_registration import (
    register_context_recall_tools,
)
from app.mcp_server.tools.maintenance_registration import (
    register_maintenance_tools,
)
from app.mcp_server.tools.memory_compact_registration import (
    register_memory_compact_tools,
)
from app.mcp_server.tools.memory_reconciliation_registration import (
    register_memory_reconciliation_tools,
)
from app.mcp_server.tools.memory_steward_registration import (
    register_memory_steward_tools,
)
from app.mcp_server.tools.obsidian_note_registration import register_obsidian_note_tools
from app.mcp_server.tools.operations_registration import register_operations_tools
from app.mcp_server.tools.skill_acquisition_registration import (
    register_skill_acquisition_tools,
)
from app.mcp_server.tools.vault_maintenance_registration import (
    register_vault_maintenance_tools,
)
from app.mcp_server.type_validate.transport_contracts import McpTransport

DEFAULT_MCP_TRANSPORT_HOST = "0.0.0.0"


def build_mcp_server(
    client: AlexandriaApiClient | None = None,
    streamable_http_path: str = "/mcp",
    transport_host: str = DEFAULT_MCP_TRANSPORT_HOST,
    local_oauth_runtime: LocalMcpOAuthRuntime | None = None,
) -> FastMCP:
    """Build the heterarchy-alexandria FastMCP server.

    Args:
        client: Optional backend API client for tests.
        streamable_http_path: FastMCP Streamable HTTP route path.
        transport_host: Host value used by FastMCP transport security.
        local_oauth_runtime: Optional self-hosted OAuth provider and settings.

    Returns:
        FastMCP server with async tool callbacks registered.
    """
    api_client = (
        AlexandriaApiClient(AlexandriaApiSettings.from_env())
        if client is None
        else client
    )
    instructions = (
        "Use these tools for Context Vault, Memory Steward operations, focused "
        "skill acquisition, and Alexandria vault maintenance through the backend "
        "HTTP API. Do not hard delete unless "
        "a tool name explicitly says delete. Submit embedding reindex work "
        "through the maintenance queue and poll its job id. For incidents, "
        "inspect operational readiness and create a recovery plan before "
        "starting or retrying a recovery run."
    )
    if local_oauth_runtime is None:
        server = FastMCP(
            "heterarchy-alexandria",
            instructions=instructions,
            json_response=True,
            host=transport_host,
            streamable_http_path=streamable_http_path,
        )
    else:
        server = FastMCP(
            "heterarchy-alexandria",
            instructions=instructions,
            json_response=True,
            host=transport_host,
            streamable_http_path=streamable_http_path,
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
    register_skill_acquisition_tools(server, api_client)
    register_context_lifecycle_tools(server, api_client)
    register_operations_tools(server, api_client)
    register_maintenance_tools(server, api_client)
    register_vault_maintenance_tools(server, api_client)
    register_obsidian_note_tools(server, api_client)
    return server


def main(argv: Sequence[str] | None = None) -> int:
    """Run the heterarchy-alexandria FastMCP server.

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
    server = build_mcp_server(transport_host=DEFAULT_MCP_TRANSPORT_HOST)
    server.run(transport=args.transport)
    return 0
