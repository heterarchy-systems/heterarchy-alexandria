"""Operational readiness read models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.memory.domain.entities.context_projection_integrity import (
    ContextProjectionIntegritySnapshot,
    unchecked_context_projection_integrity_snapshot,
)
from app.memory.domain.entities.context_read_models import ContextEmbeddingSourceStatus
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.operations.domain.entities.operational_data_integrity import (
    OperationalDataIntegritySnapshot,
    unchecked_data_integrity_snapshot,
)
from app.operations.domain.entities.operational_retrieval_canary import (
    OperationalRetrievalCanarySnapshot,
    unchecked_retrieval_canary_snapshot,
)
from app.operations.domain.entities.operational_runtime_provenance import (
    OperationalRuntimeProvenanceSnapshot,
    unchecked_runtime_provenance_snapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True)
class OperationalVaultSnapshot:
    """Vault and index state used by operational readiness."""

    exists: bool
    readable: bool
    vault_path: str
    alexandria_root: str
    alexandria_root_exists: bool
    indexed_notes: int | None
    stale_notes: int | None
    error_notes: int | None


@dataclass(frozen=True, slots=True)
class OperationalGraphSnapshot:
    """Read-only PostgreSQL graph projection status evidence."""

    status: str
    enabled: bool
    node_count: int | None
    edge_count: int | None
    run_id: str | None
    projection_revision: str | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationalDatabaseSnapshot:
    """Database state used by operational readiness."""

    reachable: bool
    integrity: str
    schema_version: str | None
    corruption_detected: bool = False


@dataclass(frozen=True, slots=True)
class OperationalRagSnapshot:
    """RAG state used by operational readiness."""

    fts: RagHealthState
    vector: RagHealthState
    embedding: RagHealthState
    effective_strategy: RagStrategy
    model_name: str
    dimensions: int
    fingerprint: JSONObject | None
    source_statuses: tuple[ContextEmbeddingSourceStatus, ...] = field(
        default_factory=tuple
    )
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class OperationalReconciliationSnapshot:
    """Memory reconciliation state used by operational readiness."""

    configured: bool
    reachable: bool
    total_contexts: int
    temporal_state_count: int
    missing_temporal_states: int
    backfill_complete: bool
    total_plans: int
    pending_review_plans: int
    total_results: int
    partial_apply_results: int
    failed_results: int
    open_conflicts: int
    reviewing_conflicts: int
    hard_delete_results: int
    latest_failure_code: str | None
    latest_failure_at: datetime | None


@dataclass(slots=True)
class OperationalReadinessSnapshot:
    """Read-only operational readiness snapshot."""

    status: OperationalReadinessStatus
    ready: bool
    checked_at: datetime
    duration_ms: int
    vault: OperationalVaultSnapshot
    database: OperationalDatabaseSnapshot
    rag: OperationalRagSnapshot
    reconciliation: OperationalReconciliationSnapshot
    active_recovery_run_id: str | None
    last_successful_recovery_run_id: str | None
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]
    next_actions: tuple[str, ...]
    data_integrity: OperationalDataIntegritySnapshot = field(
        default_factory=unchecked_data_integrity_snapshot
    )
    runtime: OperationalRuntimeProvenanceSnapshot = field(
        default_factory=unchecked_runtime_provenance_snapshot
    )
    retrieval_canary: OperationalRetrievalCanarySnapshot = field(
        default_factory=unchecked_retrieval_canary_snapshot
    )
    projection_integrity: ContextProjectionIntegritySnapshot = field(
        default_factory=unchecked_context_projection_integrity_snapshot
    )
    graph: OperationalGraphSnapshot = field(
        default_factory=lambda: OperationalGraphSnapshot(
            status="unknown",
            enabled=False,
            node_count=None,
            edge_count=None,
            run_id=None,
            projection_revision=None,
            warnings=("graph_projection_unchecked",),
        )
    )

    def __post_init__(self) -> None:
        """Normalize readiness findings and actions to immutable values."""
        self.warnings = tuple(self.warnings)
        self.blockers = tuple(self.blockers)
        self.next_actions = tuple(self.next_actions)
