"""Domain exceptions for Obsidian vault integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from app.shared.types.extra_types import JSONObject

if TYPE_CHECKING:
    from app.obsidian.domain.entities.obsidian_note import ObsidianNote


class ObsidianDomainError(RuntimeError):
    """Base Obsidian integration exception."""


class ObsidianNotFoundError(ObsidianDomainError):
    """Raised when an Obsidian note or vault resource cannot be found."""


class ObsidianValidationError(ObsidianDomainError):
    """Raised when an Obsidian request violates a storage invariant."""


class ObsidianWriteConflictError(ObsidianDomainError):
    """Raised when a canonical note changed after an agent read it."""


class ObsidianIndexWriteError(ObsidianDomainError):
    """Raised when one rebuildable Obsidian index write fails."""


class ObsidianStoredProjectionError(ObsidianValidationError):
    """Raised when Markdown is durable but a derived projection failed."""

    def __init__(
        self,
        note: ObsidianNote,
        failed_stage: Literal["metadata_index", "context_supersession"],
    ) -> None:
        """Create a typed stored-with-projection-warning failure.

        Args:
            note: Exact source readback after canonical Markdown persistence.
            failed_stage: Projection stage that failed after source durability.
        """
        super().__init__(
            "INDEX_WRITE_FAILED: canonical Markdown was preserved for reindex"
        )
        self.note = note
        self.failed_stage = failed_stage


class ObsidianGraphUnavailableError(ObsidianDomainError):
    """Raised when a graph-only read is requested without a graph provider."""


class ObsidianIdentityConflictError(ObsidianDomainError):
    """Raised before mutation when exact note selectors disagree or already exist."""

    def __init__(
        self,
        operation: str,
        requested_note_id: str | None,
        requested_path: str | None,
        id_target_path: str | None,
        path_target_id: str | None,
        recommended_operation: str,
    ) -> None:
        """Create a machine-readable identity conflict.

        Args:
            operation: Operation used by this operation.
            requested_note_id: Identifier for requested note.
            requested_path: Requested path used by this operation.
            id_target_path: Id target path used by this operation.
            path_target_id: Identifier for path target.
            recommended_operation: Recommended operation used by this operation.
        """
        super().__init__("IDENTITY_CONFLICT")
        self._detail: JSONObject = {
            "error_code": "IDENTITY_CONFLICT",
            "operation": operation,
            "requested_note_id": requested_note_id,
            "requested_path": requested_path,
            "id_target_path": id_target_path,
            "path_target_id": path_target_id,
            "mutation_performed": False,
            "recommended_operation": recommended_operation,
        }

    def route_detail(self) -> JSONObject:
        """Return the stable HTTP error detail.

        Returns:
            Result produced by route_detail.
        """
        return dict(self._detail)


class ObsidianWriteTargetNotFoundError(ObsidianDomainError):
    """Raised before mutation when an explicit update target does not exist."""

    def __init__(
        self,
        requested_note_id: str | None,
        requested_path: str | None,
    ) -> None:
        """Create a machine-readable missing-target error.

        Args:
            requested_note_id: Identifier for requested note.
            requested_path: Requested path used by this operation.
        """
        super().__init__("WRITE_TARGET_NOT_FOUND")
        self._detail: JSONObject = {
            "error_code": "WRITE_TARGET_NOT_FOUND",
            "operation": "update",
            "requested_note_id": requested_note_id,
            "requested_path": requested_path,
            "mutation_performed": False,
            "recommended_operation": "create_or_upsert",
        }

    def route_detail(self) -> JSONObject:
        """Return the stable HTTP error detail.

        Returns:
            Result produced by route_detail.
        """
        return dict(self._detail)


class ObsidianIdempotencyConflictError(ObsidianDomainError):
    """Raised when one idempotency key is reused for a different request."""

    def __init__(self) -> None:
        """Initialize ObsidianIdempotencyConflictError state and dependencies."""
        super().__init__("IDEMPOTENCY_KEY_REUSED")

    def route_detail(self) -> JSONObject:
        """Return a secret-free stable HTTP error detail.

        Returns:
            Result produced by route_detail.
        """
        return {
            "error_code": "IDEMPOTENCY_KEY_REUSED",
            "mutation_performed": False,
            "recommended_operation": "use_a_new_idempotency_key",
        }


class ObsidianCheckpointRecoveryRequiredError(ObsidianValidationError):
    """Refuse new mutation when a durable operation record cannot be trusted."""

    def __init__(self, checkpoint_id: str) -> None:
        """Retain a non-secret record identity for safe durable investigation."""
        super().__init__("CHECKPOINT_RECOVERY_REQUIRED")
        self.checkpoint_id = checkpoint_id

    def route_detail(self) -> JSONObject:
        """Return actionable failure without treating corruption as absence."""
        return {
            "error_code": "CHECKPOINT_RECOVERY_REQUIRED",
            "cause": "The existing durable operation checkpoint is invalid or unreadable.",
            "affected_capability": "mutation_replay",
            "retryable": False,
            "checkpoint_id": self.checkpoint_id,
            "safe_next_action": "Verify the canonical source and inspect the existing recovery plan before repairing this checkpoint.",
            "recommended_action": "durable_readback_before_recovery",
            "unsafe_action_warning": "Do not delete the checkpoint or change the key to repeat an unknown mutation.",
        }
