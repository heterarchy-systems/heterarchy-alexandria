"""Authentication contracts for the public MCP HTTP boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

MCP_OAUTH_PROTECTED_RESOURCE_PATH: Final[str] = "/.well-known/oauth-protected-resource"


@dataclass(frozen=True)
class McpHttpAuthResult:
    """Authorization result for one MCP HTTP request."""

    allowed: bool
    status_code: int = 200
    detail: str = "ok"
    headers: Mapping[str, str] = MappingProxyType({})
