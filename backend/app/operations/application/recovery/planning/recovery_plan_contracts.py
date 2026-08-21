"""Request contract for read-only operational recovery planning."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecoveryPlanRequest:
    """Request data for a recovery dry-run plan."""

    trigger: str = "manual"
    actor: str = "operator"
    idempotency_key: str | None = None
    parent_run_id: str | None = None
