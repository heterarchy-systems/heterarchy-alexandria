"""Recovery dry-run plan read models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)


@dataclass(slots=True)
class RecoverySourceSnapshot:
    """Read-only source preservation preflight evidence."""

    vault_path: str
    alexandria_root: str
    managed_markdown_count: int
    representative_path: str | None
    representative_sha256: str | None
    disk_free_bytes: int | None
    access_error: str | None = None
    markdown_manifest: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze the source manifest mapping."""
        self.markdown_manifest = MappingProxyType(dict(self.markdown_manifest))


@dataclass(frozen=True, slots=True)
class RecoveryPlanStep:
    """One planned recovery step."""

    code: str
    title: str
    mutates_state: bool


@dataclass(slots=True)
class RecoveryPlan:
    """Read-only recovery dry-run plan."""

    id: str
    parent_run_id: str | None
    idempotency_key: str
    trigger: str
    actor: str
    status: OperationalReadinessStatus
    created_at: datetime
    dry_run: bool
    automatic_execution_allowed: bool
    diagnosis: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    source_snapshot: RecoverySourceSnapshot
    steps: tuple[RecoveryPlanStep, ...]
    estimated_reindex_scope: Mapping[str, int | str | None]
    service_impact: tuple[str, ...]
    next_actions: tuple[str, ...]
    readiness: OperationalReadinessSnapshot
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize recovery plan collections to immutable values."""
        self.diagnosis = tuple(self.diagnosis)
        self.blocked_reasons = tuple(self.blocked_reasons)
        self.steps = tuple(self.steps)
        self.estimated_reindex_scope = MappingProxyType(
            dict(self.estimated_reindex_scope)
        )
        self.service_impact = tuple(self.service_impact)
        self.next_actions = tuple(self.next_actions)
        self.warnings = tuple(self.warnings)
