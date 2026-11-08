"""Read-only recovery lock and successful-run history lookup."""

from __future__ import annotations

from pathlib import Path

from app.operations.application.recovery.planning.operational_recovery_paths import (
    recovery_directory as _recovery_dir,
)
from app.operations.domain.recovery_state_constants import (
    UNREADABLE_ACTIVE_RECOVERY_RUN_ID,
)
from app.shared.serialization.orjson_codec import loads_json
from app.shared.types.extra_types import JSONObject


def active_recovery_run_id() -> str | None:
    """Return the active recovery run identifier from the durable lock file.

    Returns:
        Active run identifier, an unreadable sentinel if the lock file is
        corrupted or missing its run id, or None when no active lock exists.
    """
    path = _recovery_dir() / "active-run.json"
    if not path.exists():
        return None
    payload = _load_recovery_json(path)
    if payload is None:
        return UNREADABLE_ACTIVE_RECOVERY_RUN_ID
    run_id = payload.get("run_id")
    return UNREADABLE_ACTIVE_RECOVERY_RUN_ID if run_id is None else str(run_id)


def last_successful_recovery_run_id() -> str | None:
    """Return the identifier of the most recently completed recovery run.

    Returns:
        Run identifier of the latest COMPLETED manifest, or None when no
        completed recovery run exists.
    """
    recovery_dir = _recovery_dir()
    if not recovery_dir.exists():
        return None
    completed: list[tuple[str, str]] = []
    for manifest_path in recovery_dir.glob("*/recovery-run.json"):
        payload = _load_recovery_json(manifest_path)
        if payload is None or payload.get("status") != "COMPLETED":
            continue
        run_id = payload.get("id")
        if run_id is None:
            continue
        finished_at = (
            payload.get("finished_at")
            or payload.get("updated_at")
            or payload.get("started_at")
            or ""
        )
        completed.append((str(finished_at), str(run_id)))
    if not completed:
        return None
    return max(completed)[1]


def _load_recovery_json(path: Path) -> JSONObject | None:
    """Read and decode a persisted recovery JSON object from disk.

    Args:
        path: Filesystem path to the JSON record.

    Returns:
        Decoded JSON object, or None on I/O errors, parse failures, or
        non-object payloads.
    """
    try:
        payload = loads_json(path.read_bytes())
    except OSError, ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload
