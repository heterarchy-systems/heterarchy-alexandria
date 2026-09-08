"""Typed application contracts for aggregate memory-cycle execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.memory_cycle_enums import MemoryCycleOperation


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCycleRequest:
    """Bounded dry-run or apply request for one project memory window."""

    operation: MemoryCycleOperation
    window_start: datetime
    window_end: datetime
    idempotency_key: str
    project: str
    workspace_id: str | None = None
    scope: ContextScope = ContextScope.PROJECT
    max_contexts: int = 100
    expected_plan_hash: str | None = None
