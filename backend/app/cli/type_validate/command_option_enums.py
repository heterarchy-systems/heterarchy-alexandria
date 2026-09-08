"""Feature-owned command option enums."""

from __future__ import annotations

from enum import StrEnum


class RequiredMcpTool(StrEnum):
    """MCP tools required for Memory Steward maintenance checks."""

    MEMORY_STEWARD_READINESS = "alexandria_memory_steward_readiness"
    MEMORY_STEWARD_REFRESH_CURRENT_COMPACT = (
        "alexandria_memory_steward_refresh_current_compact"
    )
