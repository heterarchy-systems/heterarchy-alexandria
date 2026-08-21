"""Feature-owned mcp transport enums."""

from __future__ import annotations

from enum import StrEnum


class McpTransport(StrEnum):
    """Supported MCP server transport names."""

    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"
