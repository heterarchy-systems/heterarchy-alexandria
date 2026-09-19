"""Tool-set revision metadata for the Alexandria MCP tools/list surface.

The revision is observation and cache-invalidation metadata only. It never
gates tool activation and never replaces effect-time authority checks, so
stale tool calls keep failing at the same authority boundaries as before.
"""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from typing import Any, cast

from mcp.server import MCPServer
from mcp.server.lowlevel.server import LifespanResultT
from mcp_types import Tool

from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONValue

TOOLSET_REVISION_META_KEY = "alexandria.toolset_revision"
"""Per-tool ``_meta`` key carrying the tool-set revision on tools/list output."""

_TOOLSET_REVISION_HEX_LENGTH = 16
"""64-bit hex prefix: collision-resistant enough for cache invalidation."""


def compute_toolset_revision(tools: Iterable[Tool]) -> str:
    """Compute the deterministic revision over the (name, input schema) set.

    Each tool contributes its name plus the canonical JSON serialization of its
    input schema (sorted object keys, compact separators), so dictionary key
    order and whitespace cannot change the digest. Contributions are sorted by
    tool name, so registration or module/file order cannot change the digest.
    The revision is the SHA-256 hex digest truncated to 16 hex characters.

    Args:
        tools: Tool definitions exposed on the tools/list surface.

    Returns:
        Stable tool-set revision string.
    """
    entries = sorted(
        (
            tool.name,
            dumps_canonical_json(cast(JSONValue, tool.input_schema)).decode("utf-8"),
        )
        for tool in tools
    )
    revision_material = "\n".join(
        f"{name}\x1f{schema_json}" for name, schema_json in entries
    )
    return sha256(revision_material.encode("utf-8")).hexdigest()[
        :_TOOLSET_REVISION_HEX_LENGTH
    ]


class ToolsetRevisionMCPServer(MCPServer[LifespanResultT]):
    """MCPServer that stamps the tool-set revision onto tools/list entries.

    The inherited tools/list handler forwards ``self.list_tools()`` verbatim,
    so overriding ``list_tools()`` covers both direct discovery calls and the
    wire response without touching the vendored SDK. The revision is recomputed
    from the live tool set on each call, leaving no mutable server state, and
    it is attached as per-tool ``_meta`` only: discovery metadata stays valid
    regardless of per-caller activation or permission state.
    """

    async def list_tools(self) -> list[Tool]:
        """List tools with the tool-set revision stamped into each ``_meta``.

        Returns:
            Tool definitions whose ``_meta`` carries the tool-set revision.
        """
        tools = await super().list_tools()
        revision = compute_toolset_revision(tools)
        return [_stamped_tool(tool, revision) for tool in tools]


def _stamped_tool(tool: Tool, revision: str) -> Tool:
    """Return a copy of one tool definition with the revision meta attached.

    Args:
        tool: Tool definition produced by the parent discovery implementation.
        revision: Computed tool-set revision.

    Returns:
        Tool definition copy carrying the revision under ``_meta``.
    """
    # FastMCP tool.meta is an untyped third-party boundary (type-contract: allow-any).
    meta: dict[str, Any] = dict(tool.meta) if tool.meta is not None else {}
    meta[TOOLSET_REVISION_META_KEY] = revision
    return tool.model_copy(update={"meta": meta})
