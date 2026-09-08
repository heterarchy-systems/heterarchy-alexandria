"""Domain failures for the managed specification trust boundary."""

from __future__ import annotations

from app.obsidian.domain.event_enum.managed_spec_enums import (
    ManagedSpecFailureCode,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianDomainError
from app.shared.types.extra_types import JSONObject


class ManagedSpecError(ObsidianDomainError):
    """Expose a stable, actionable managed-spec failure to interface layers."""

    def __init__(
        self,
        code: ManagedSpecFailureCode,
        cause: str,
        *,
        retryable: bool,
        safe_next_action: str,
        recommended_action: str,
        unsafe_action_warning: str | None = None,
        recovery_run_id: str | None = None,
    ) -> None:
        """Create a structured managed-spec failure."""
        super().__init__(code.value)
        self.code = code
        self.cause = cause
        self.retryable = retryable
        self.safe_next_action = safe_next_action
        self.recommended_action = recommended_action
        self.unsafe_action_warning = unsafe_action_warning
        self.recovery_run_id = recovery_run_id

    def route_detail(self) -> JSONObject:
        """Return a stable, secret-free route payload."""
        return {
            "error_code": self.code.value,
            "cause": self.cause,
            "affected_capability": "managed_spec_execution",
            "retryable": self.retryable,
            "safe_next_action": self.safe_next_action,
            "recommended_action": self.recommended_action,
            "unsafe_action_warning": self.unsafe_action_warning,
            "recovery_run_id": self.recovery_run_id,
        }
