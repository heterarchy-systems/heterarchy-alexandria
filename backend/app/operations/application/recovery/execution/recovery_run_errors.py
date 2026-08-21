"""Domain-facing failures raised by operational recovery runs."""

from __future__ import annotations


class RecoveryInProgressError(RuntimeError):
    """Raised when a different recovery run is already active."""

    def __init__(self, run_id: str, idempotency_key: str | None) -> None:
        """Create error.

        Args:
            run_id: Active recovery run id.
            idempotency_key: Active recovery idempotency key when known.
        """
        super().__init__("recovery is already in progress")
        self.run_id = run_id
        self.idempotency_key = idempotency_key


class RecoveryStepFailedError(RuntimeError):
    """Raised when a recovery step result must fail the run."""

    def __init__(self, error_code: str, error_summary: str) -> None:
        """Create step failure.

        Args:
            error_code: PRD recovery error code.
            error_summary: Human-readable failure summary.
        """
        super().__init__(error_summary)
        self.error_code = error_code
        self.error_summary = error_summary
