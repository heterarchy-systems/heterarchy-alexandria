"""Cross-thread admission and ownership fences for persistent recovery state."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from tests.operations.test_recovery_run_service import _plan

from app.operations.application.recovery.execution.recovery_run_errors import (
    RecoveryInProgressError,
)
from app.operations.application.recovery.execution.recovery_run_manifest import (
    _checkpoint_active_step,
    _clear_active_lock,
    _read_active_lock,
    _write_active_lock,
)


def test_only_one_recovery_admission_can_claim_active_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    start = Barrier(2)

    def claim(key: str) -> str | None:
        start.wait()
        try:
            _write_active_lock(_plan(key=key, automatic=True, steps=()))
        except RecoveryInProgressError:
            return None
        return key

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("first", "second")))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    active = _read_active_lock()
    assert active is not None
    assert active.run_id == f"run-{winners[0]}"


def test_foreign_recovery_cannot_replace_or_clear_current_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    owner = _plan(key="owner", automatic=True, steps=())
    foreign = _plan(key="foreign", automatic=True, steps=())
    _write_active_lock(owner)
    with pytest.raises(RecoveryInProgressError):
        _checkpoint_active_step(foreign, "reindex_vault")
    _clear_active_lock(foreign)
    active = _read_active_lock()
    assert active is not None and active.run_id == owner.id
    _checkpoint_active_step(owner, "snapshot_sources")
    active = _read_active_lock()
    assert active is not None and active.current_step == "snapshot_sources"
    _clear_active_lock(owner)
    assert _read_active_lock() is None
