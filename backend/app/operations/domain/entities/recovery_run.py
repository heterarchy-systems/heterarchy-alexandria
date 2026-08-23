"""Recovery run read models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.operations.domain.entities.recovery_plan import (
    RecoveryPlanStep,
    RecoverySourceSnapshot,
)
from app.operations.domain.event_enum.operational_recovery_enums import (
    RecoveryRunStatus,
    RecoveryStepStatus,
)
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True)
class RecoveryRunStepResult:
    """One recovery step execution result."""

    code: str
    status: RecoveryStepStatus
    attempts: int
    started_at: datetime | None
    finished_at: datetime | None
    input_hash: str
    result: JSONObject = field(default_factory=dict)


@dataclass(slots=True)
class RecoveryRun:
    """Executed recovery run state."""

    id: str
    parent_run_id: str | None
    idempotency_key: str
    trigger: str
    actor: str
    status: RecoveryRunStatus
    current_step: str | None
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    source_snapshot: RecoverySourceSnapshot
    diagnosis: tuple[str, ...]
    planned_steps: tuple[RecoveryPlanStep, ...]
    step_results: tuple[RecoveryRunStepResult, ...]
    rebuild_results: JSONObject
    verification_results: JSONObject
    error_code: str | None
    error_summary: str | None
    next_actions: tuple[str, ...]
    manifest_path: str

    def __post_init__(self) -> None:
        """Normalize recovery run collections to immutable values."""
        self.diagnosis = tuple(self.diagnosis)
        self.planned_steps = tuple(self.planned_steps)
        self.step_results = tuple(self.step_results)
        self.next_actions = tuple(self.next_actions)
