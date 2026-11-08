"""Stable filesystem paths for recovery locks and run manifests."""

from __future__ import annotations

from pathlib import Path

from app.operations.domain.entities.recovery_plan import RecoveryPlan

RECOVERY_DIRECTORY_NAME = ".alexandria-recovery"


def recovery_directory() -> Path:
    """Return the persistent application recovery directory.

    Returns:
        Directory used for recovery manifests and coordination state.
    """
    return Path.cwd() / "data" / RECOVERY_DIRECTORY_NAME


def manifest_path(plan: RecoveryPlan) -> Path:
    """Return the durable manifest file path for a recovery plan.

    Args:
        plan: Recovery plan whose run id locates the manifest directory.

    Returns:
        Filesystem path to the plan's recovery-run.json file.
    """
    return manifest_path_by_id(run_id=plan.id)


def manifest_path_by_id(run_id: str) -> Path:
    """Return the durable manifest file path for a recovery run identifier.

    Args:
        run_id: Recovery run identifier.

    Returns:
        Filesystem path to the run's recovery-run.json file.
    """
    return recovery_directory() / run_id / "recovery-run.json"


def active_lock_path() -> Path:
    """Return the filesystem path for the active recovery lock record.

    Returns:
        Filesystem path to the active-run.json lock record.
    """
    return recovery_directory() / "active-run.json"
