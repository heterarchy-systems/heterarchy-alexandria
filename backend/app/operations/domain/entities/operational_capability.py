"""Independent readiness states for platform capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.operations.domain.event_enum.operational_capability_enums import (
    OperationalCapabilityFreshness,
    OperationalCapabilityState,
)


@dataclass(frozen=True, slots=True)
class OperationalCapability:
    """Readiness and findings for one independently usable capability."""

    state: OperationalCapabilityState
    ready: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    source_revision: str | None = None
    projection_revision: str | None = None
    freshness: OperationalCapabilityFreshness = OperationalCapabilityFreshness.UNKNOWN


@dataclass(frozen=True, slots=True)
class OperationalCapabilitySnapshot:
    """Core/semantic summaries plus independent capability evidence."""

    checked_at: datetime
    core_memory: OperationalCapability
    semantic_retrieval: OperationalCapability
    source: OperationalCapability
    metadata_index: OperationalCapability
    fts: OperationalCapability
    vector: OperationalCapability
    embedding: OperationalCapability
    graph: OperationalCapability
    reconciliation: OperationalCapability
