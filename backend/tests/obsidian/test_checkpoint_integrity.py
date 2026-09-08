"""Invalid durable checkpoints must never be treated as a fresh operation."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
)


@dataclass(frozen=True)
class _Checkpoint:
    request_hash: str
    source_id: str


def test_missing_checkpoint_is_distinct_from_invalid_checkpoint(tmp_path: Path) -> None:
    store = ObsidianReportBundleRunStore(tmp_path)
    adapter = TypeAdapter(_Checkpoint)
    assert store.load_typed("missing", adapter) is None
    store.save("existing", {"foreign_record": "must not become fresh admission"})
    before = store.load("existing")
    with pytest.raises(ObsidianCheckpointRecoveryRequiredError) as caught:
        store.load_typed("existing", adapter)
    assert caught.value.route_detail()["retryable"] is False
    assert store.load("existing") == before


def test_structurally_valid_foreign_operation_is_rejected(tmp_path: Path) -> None:
    store = ObsidianReportBundleRunStore(tmp_path)
    adapter = TypeAdapter(_Checkpoint)
    checkpoint = _Checkpoint(request_hash="hash", source_id="source")
    store.save_typed("managed-spec:run", checkpoint, adapter)
    assert store.load_typed("managed-spec:run", adapter) == checkpoint
    record = store.load("managed-spec:run")
    assert record is not None
    record["kind"] = "foreign-operation"
    store.save("managed-spec:run", record)
    with pytest.raises(ObsidianCheckpointRecoveryRequiredError):
        store.load_typed("managed-spec:run", adapter)
    assert store.load("managed-spec:run") == record


@pytest.mark.parametrize("body", ["[]", "null", "{broken"])
def test_unreadable_checkpoint_fails_closed(tmp_path: Path, body: str) -> None:
    store = ObsidianReportBundleRunStore(tmp_path)
    store.save("existing", {"request_hash": "hash", "source_id": "source"})
    path = next((tmp_path / ".alexandria" / "report-bundle-runs").glob("*.json"))
    path.write_text(body)
    with pytest.raises(ObsidianCheckpointRecoveryRequiredError):
        store.load_typed("existing", TypeAdapter(_Checkpoint))
    assert path.read_text() == body
