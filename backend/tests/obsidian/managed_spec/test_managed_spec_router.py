"""HTTP route evidence for managed-spec output failure mapping."""

from __future__ import annotations

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from app.main import app
from app.obsidian.domain.contracts.managed_spec_contracts import (
    ManagedSpecCompleteRequest,
)
from app.obsidian.domain.verified_upsert_exceptions import (
    ObsidianVerifiedUpsertRecoveryRequiredError,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
    ObsidianWriteConflictError,
)

pytestmark = pytest.mark.usefixtures("restore_default_app_wiring")


class _CompleteFailureService:
    """Typed managed-spec service double that fails during output completion."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def complete(self, request: ManagedSpecCompleteRequest) -> object:
        """Raise the configured output-writer failure."""
        del request
        raise self._error


def _complete_payload() -> dict[str, str]:
    """Return one schema-valid managed-spec completion payload."""
    return {
        "operation": "complete",
        "idempotency_key": "http-run-1",
        "prepared_envelope_hash": "a" * 64,
        "output_title": "Evidence output",
        "output_body": "# Durable evidence\n",
    }


@pytest.mark.parametrize(
    "error",
    [
        ObsidianWriteConflictError("output changed"),
        ObsidianVerifiedUpsertRecoveryRequiredError(
            idempotency_key="http-run-1",
            canonical_path="Alexandria/Jobs/output.md",
        ),
    ],
    ids=["write-conflict", "verified-upsert-recovery"],
)
def test_managed_spec_complete_maps_output_writer_failures_to_http_409(
    error: Exception,
) -> None:
    """Output writer conflicts preserve typed route detail and HTTP 409."""
    failure_service = _CompleteFailureService(error)
    with (
        app.state.container.obsidian.managed_spec_service.override(
            providers.Object(failure_service)
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/obsidian/managed-specs/execute",
            json=_complete_payload(),
        )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    if isinstance(error, ObsidianVerifiedUpsertRecoveryRequiredError):
        assert detail["error_code"] == "VERIFIED_UPSERT_RECOVERY_REQUIRED"
        assert detail["mutation_performed"] is False
        assert detail["safe_next_action"]
    else:
        assert detail == "output changed"


def test_managed_spec_checkpoint_mapping_keeps_http_409_and_typed_detail() -> None:
    """The specific checkpoint override remains ahead of shared validation mapping."""
    failure_service = _CompleteFailureService(
        ObsidianCheckpointRecoveryRequiredError("checkpoint-1")
    )
    with (
        app.state.container.obsidian.managed_spec_service.override(
            providers.Object(failure_service)
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/obsidian/managed-specs/execute",
            json=_complete_payload(),
        )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "CHECKPOINT_RECOVERY_REQUIRED"
    assert detail["checkpoint_id"] == "checkpoint-1"
