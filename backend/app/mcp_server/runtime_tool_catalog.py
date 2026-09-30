"""Process-cached catalog of live registered MCP tool names."""

from __future__ import annotations

from hashlib import sha256
from typing import cast

from app.operations.domain.entities.skill_contract import SkillRuntimeContract
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONValue

_CACHED_TOOL_NAMES: tuple[str, ...] | None = None
_CACHED_FINGERPRINT: str | None = None


def registered_runtime_tool_names() -> tuple[str, ...]:
    """Return every live registered MCP tool name.

    The names come from the real server assembly, so the catalog always
    reflects the actually registered toolset. The build is cached for the
    process lifetime because registration is static per process.

    Returns:
        Sorted registered tool names.
    """
    global _CACHED_TOOL_NAMES
    global _CACHED_FINGERPRINT
    if _CACHED_TOOL_NAMES is None:
        from app.mcp_server.backend_api_client import (
            AlexandriaApiClient,
            AlexandriaApiSettings,
        )
        from app.mcp_server.server_runtime import build_mcp_server

        client = AlexandriaApiClient(
            AlexandriaApiSettings(base_url="http://localhost:8000", timeout=1.0)
        )
        server = build_mcp_server(client=client)
        _CACHED_TOOL_NAMES = tuple(
            sorted(tool.name for tool in server._tool_manager.list_tools())
        )
        manifest = [
            {"name": tool.name, "input": tool.parameters, "output": tool.output_schema}
            for tool in sorted(
                server._tool_manager.list_tools(), key=lambda item: item.name
            )
        ]
        _CACHED_FINGERPRINT = sha256(
            dumps_canonical_json(cast(JSONValue, manifest))
        ).hexdigest()
    return _CACHED_TOOL_NAMES


def registered_skill_runtime_contract(
    runtime_revision: str | None,
) -> SkillRuntimeContract:
    """Expose full input/output manifest identity for the loaded server assembly.

    Args:
        runtime_revision: Build-owned running source revision, absent if unverified.

    Returns:
        Loaded capability fingerprint and explicit revision evidence.
    """
    names = registered_runtime_tool_names()
    assert _CACHED_FINGERPRINT is not None
    return SkillRuntimeContract(
        tool_names=names,
        capability_fingerprint=_CACHED_FINGERPRINT,
        runtime_revision=runtime_revision,
        source_repo_revision=runtime_revision,
    )
