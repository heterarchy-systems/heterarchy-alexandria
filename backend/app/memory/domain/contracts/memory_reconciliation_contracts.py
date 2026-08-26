"""Application input contracts for memory reconciliation use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    MemorySourceReference,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    RagStrategy,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCandidateCreate:
    """Caller-supplied fields used to create a normalized memory candidate."""

    title: str
    body: str
    scope: ContextScope
    project: str | None = None
    workspace_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    canonical_claims: tuple[CanonicalClaim, ...] = ()
    tags: tuple[str, ...] = ()
    source_refs: tuple[MemorySourceReference, ...] = ()
    recorded_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    requested_lifecycle: str = "active"
    candidate_id: str | None = None
    source_identity: str | None = None
    graph_neighbors: tuple[str, ...] = ()
    lineage_ancestors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryReconciliationPreviewRequest:
    """Preview request with an optional caller-controlled idempotency key."""

    candidate: MemoryCandidateCreate
    idempotency_key: str | None = None
    recall_limit: int = 20


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryTemporalRecallRequest:
    """Recall Contexts through an explicit temporal perspective."""

    query: str
    mode: MemoryTemporalRecallMode = MemoryTemporalRecallMode.CURRENT
    as_of: datetime | None = None
    strategy: RagStrategy = RagStrategy.HYBRID
    limit: int = 5
    project: str | None = None
    kind: ContextKind | None = None
    include_scopes: tuple[ContextScope, ...] = ()
    workspace_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    include_lifecycle_statuses: tuple[ContextRecallLifecycleStatus, ...] = ()
