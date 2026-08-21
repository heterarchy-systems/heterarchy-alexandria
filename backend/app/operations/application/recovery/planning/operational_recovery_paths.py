"""Stable filesystem paths for recovery locks and run manifests."""

from __future__ import annotations

from pathlib import Path

RECOVERY_DIRECTORY_NAME = ".alexandria-recovery"


def recovery_directory() -> Path:
    """Return the persistent application recovery directory.

    Returns:
        Directory used for recovery manifests and coordination state.
    """
    return Path.cwd() / "data" / RECOVERY_DIRECTORY_NAME
