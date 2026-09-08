"""Independent readiness states for platform capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.operations.domain.event_enum.operational_capability_enums import (
    OperationalCapabilityState,
)


@dataclass(frozen=True, slots=True)
class OperationalCapability:
    """Readiness and findings for one independently usable capability."""

    state: OperationalCapabilityState
    ready: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperationalCapabilitySnapshot:
    """Core memory and semantic retrieval are assessed independently."""

    checked_at: datetime
    core_memory: OperationalCapability
    semantic_retrieval: OperationalCapability
