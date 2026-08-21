"""Typer commands for Alexandria MCP server launch and smoke checks."""

from __future__ import annotations

from collections.abc import Sequence

import httpx
import typer

from app.cli.output import run_json_command
from app.cli.type_validate.command_options import (
    DEFAULT_REQUIRED_MCP_TOOLS,
    McpUrlOption,
    RequiredToolOption,
    TransportOption,
)
from app.cli.type_validate.mcp_protocol_payload_contracts import (
    McpSmokeToolsResultPayload,
    decode_mcp_json_response,
    mcp_smoke_ok,
    mcp_tool_names,
)
from app.mcp_server import server_runtime
from app.mcp_server.backend_api_client import AlexandriaApiError, AlexandriaApiSettings
from app.mcp_server.type_validate.mcp_transport_enums import McpTransport
from app.shared.types.extra_types import JSONValue

mcp_app = typer.Typer(
    help="Run MCP server and live MCP checks.",
    no_args_is_help=True,
    add_completion=False,
)


class McpToolSmokeChecker:
    """Check live Streamable HTTP MCP tool exposure for required tools."""

    def __init__(
        self,
        settings: AlexandriaApiSettings,
        mcp_url: str | None,
        required_tools: Sequence[str],
    ) -> None:
        self._settings = settings
        self._endpoint = mcp_url or f"{settings.base_url.rstrip('/')}/mcp/"
        self._required_tools = tuple(required_tools)

    async def run(self) -> JSONValue:
        """Return smoke-check status for the configured MCP endpoint.

        Returns:
            JSON-compatible smoke-check payload.
        """
        headers = self._headers()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._settings.timeout)
            ) as client:
                init_response = await client.post(
                    self._endpoint,
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "heterarchy-alexandria-cli-smoke",
                                "version": "0.1.0",
                            },
                        },
                    },
                )
                init_response.raise_for_status()
                list_headers = self._session_headers(
                    headers,
                    init_response.headers.get("mcp-session-id"),
                )
                tools_response = await client.post(
                    self._endpoint,
                    headers=list_headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    },
                )
                tools_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = exc.response.text
            raise AlexandriaApiError(exc.response.status_code, message) from exc
        except httpx.RequestError as exc:
            raise AlexandriaApiError(0, str(exc)) from exc

        tool_names = mcp_tool_names(decode_mcp_json_response(tools_response.text))
        missing = [tool for tool in self._required_tools if tool not in tool_names]
        result = McpSmokeToolsResultPayload(
            ok=not missing,
            mcp_url=self._endpoint,
            required_tools=self._required_tools,
            missing_tools=tuple(missing),
            tool_count=len(tool_names),
        )
        return result.model_dump(mode="json")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        return headers

    def _session_headers(
        self,
        headers: dict[str, str],
        session_id: str | None,
    ) -> dict[str, str]:
        list_headers = dict(headers)
        if session_id:
            list_headers["mcp-session-id"] = session_id
        return list_headers


@mcp_app.command("serve")
def _serve(
    transport: TransportOption = McpTransport.STDIO,
) -> int:
    """Serve Alexandria MCP using the selected transport."""
    return server_runtime.main(["--transport", transport.value])


@mcp_app.command("smoke-tools")
def _smoke_tools_command(
    mcp_url: McpUrlOption = None,
    required_tool: RequiredToolOption = None,
) -> int:
    """Check that required live MCP tools are exposed."""
    required_tools = required_tool or list(DEFAULT_REQUIRED_MCP_TOOLS)

    async def operation() -> JSONValue:
        return await _mcp_smoke_tools(
            settings=AlexandriaApiSettings.from_env(),
            mcp_url=mcp_url,
            required_tools=required_tools,
        )

    exit_code = run_json_command(
        operation,
        error_prefix="Alexandria MCP smoke error",
        attention_required=lambda payload: not mcp_smoke_ok(payload),
    )
    return exit_code


async def _mcp_smoke_tools(
    settings: AlexandriaApiSettings,
    mcp_url: str | None,
    required_tools: Sequence[str],
) -> JSONValue:
    checker = McpToolSmokeChecker(
        settings=settings,
        mcp_url=mcp_url,
        required_tools=required_tools,
    )
    return await checker.run()
