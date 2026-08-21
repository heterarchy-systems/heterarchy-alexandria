"""Feature-owned command option enums."""

from __future__ import annotations

from enum import StrEnum


class RequiredMcpTool(StrEnum):
    """MCP tools required for Memory Steward and Vault maintenance checks."""

    MEMORY_STEWARD_READINESS = "alexandria_memory_steward_readiness"
    MEMORY_STEWARD_REFRESH_CURRENT_COMPACT = (
        "alexandria_memory_steward_refresh_current_compact"
    )
    VAULT_REVIEW_QUEUE = "alexandria_vault_review_queue"
    VAULT_REVIEW_MOVE_PLAN = "alexandria_vault_review_move_plan"
    VAULT_REVIEW_APPLY_MOVES = "alexandria_vault_review_apply_moves"
