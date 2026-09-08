"""Stable recovery failures for the verified logical upsert boundary."""

from __future__ import annotations

from app.shared.exceptions.obsidian_exceptions import ObsidianWriteConflictError
from app.shared.types.extra_types import JSONObject


class ObsidianVerifiedUpsertRecoveryRequiredError(ObsidianWriteConflictError):
    """Block mutation when an admitted write has no provable source readback."""

    def __init__(self, *, idempotency_key: str, canonical_path: str) -> None:
        """Create one durable-recovery-required failure."""
        self.idempotency_key = idempotency_key
        self.canonical_path = canonical_path
        super().__init__(
            "VERIFIED_UPSERT_RECOVERY_REQUIRED: admitted mutation has no "
            "provable canonical source; mutation was not retried"
        )

    def route_detail(self) -> JSONObject:
        """Return actionable, secret-free recovery guidance."""
        return {
            "error_code": "VERIFIED_UPSERT_RECOVERY_REQUIRED",
            "cause": str(self),
            "affected_capability": "verified_upsert_recovery",
            "retryable": False,
            "safe_next_action": (
                "inspect the durable checkpoint and restore or reconcile the "
                "canonical source before retrying"
            ),
            "recommended_action": (
                "do not create a replacement with the same logical identity"
            ),
            "unsafe_action_warning": (
                "a fresh retry could create a duplicate active logical note"
            ),
            "recovery_plan_run_id": None,
            "idempotency_key": self.idempotency_key,
            "canonical_path": self.canonical_path,
            "mutation_performed": False,
        }
