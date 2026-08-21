"""Operational recovery path contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.operations.application.recovery.planning.operational_recovery_paths import (
    RECOVERY_DIRECTORY_NAME,
    recovery_directory,
)
from app.operations.application.recovery.execution.recovery_run_manifest import (
    _manifest_path_by_id,
)


def test_recovery_directory_uses_persistent_data_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery evidence should persist under the application data root."""
    monkeypatch.chdir(tmp_path)

    assert recovery_directory() == (tmp_path / "data" / RECOVERY_DIRECTORY_NAME)


def test_manifest_path_uses_persistent_recovery_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery run manifests should use the persistent application path."""
    monkeypatch.chdir(tmp_path)

    assert _manifest_path_by_id(run_id="run-1") == (
        tmp_path / "data" / RECOVERY_DIRECTORY_NAME / "run-1" / "recovery-run.json"
    )
