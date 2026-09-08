"""Strict boundary contract tests for verified upsert and verify."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.domain.verified_upsert_exceptions import (
    ObsidianVerifiedUpsertRecoveryRequiredError,
)
from app.obsidian.interface.schemas.obsidian.obsidian_verified_upsert_schema import (
    ObsidianVerifiedUpsertRequestSchema,
    ObsidianVerifiedUpsertSelectorSchema,
)
from app.shared.serialization.orjson_codec import dumps_json


def test_verified_upsert_request_uses_shared_identity_and_typed_provenance() -> None:
    """The HTTP request rejects arbitrary metadata and restores typed identity."""
    request = ObsidianVerifiedUpsertRequestSchema.model_validate_json(
        dumps_json(
            {
                "identity": {
                    "project": "Project",
                    "report": "Morning Read",
                    "date": "2026-09-08",
                    "entity": "ETH",
                },
                "title": "ETH Morning Read",
                "body": "fact",
                "alexandria_type": "job_plan",
                "idempotency_key": "run-1",
                "tags": ["evidence", "evidence"],
                "provenance": {
                    "source_actor_id": "agent-1",
                    "source_run_id": "run-1",
                },
            }
        )
    )

    command = request.to_command()

    assert command.identity.project == "Project"
    assert command.alexandria_type is AlexandriaNoteType.JOB_PLAN
    assert command.tags == ("evidence",)
    assert command.provenance["source_actor_id"] == "agent-1"

    with pytest.raises(ValidationError):
        ObsidianVerifiedUpsertRequestSchema.model_validate_json(
            dumps_json(
                {
                    "identity": {
                        "project": "Project",
                        "report": "Morning Read",
                        "date": "2026-09-08",
                        "entity": "ETH",
                    },
                    "title": "ETH Morning Read",
                    "body": "fact",
                    "alexandria_type": "job_plan",
                    "idempotency_key": "run-1",
                    "metadata": {"unsafe": True},
                }
            )
        )


def test_verified_selector_requires_one_selector() -> None:
    """Verify cannot silently fall back to an unscoped or ambiguous read."""
    with pytest.raises(ValidationError):
        ObsidianVerifiedUpsertSelectorSchema.model_validate({})

    with pytest.raises(ValidationError):
        ObsidianVerifiedUpsertSelectorSchema.model_validate(
            {"note_id": "note-1", "path": "Alexandria/Jobs/note-1.md"}
        )


def test_verified_selector_domain_guard_remains_defensive() -> None:
    """The internal selector contract still rejects bypassed invalid construction."""
    schema = ObsidianVerifiedUpsertSelectorSchema.model_construct(
        identity=None,
        note_id=None,
        path=None,
    )

    with pytest.raises(ValueError):
        schema.to_selector()


def test_verified_selector_http_rejects_empty_and_multiple_selectors() -> None:
    """HTTP validation rejects invalid selectors before service execution."""
    with TestClient(app, raise_server_exceptions=False) as client:
        empty = client.post("/obsidian/verified-upsert/verify", json={})
        multiple = client.post(
            "/obsidian/verified-upsert/verify",
            json={"note_id": "note-1", "path": "Alexandria/Jobs/note-1.md"},
        )

    assert empty.status_code == 422, empty.text
    assert multiple.status_code == 422, multiple.text


def test_verified_recovery_error_exposes_safe_next_action() -> None:
    """Unknown-after-admission failures provide bounded recovery guidance."""
    detail = ObsidianVerifiedUpsertRecoveryRequiredError(
        idempotency_key="run-1",
        canonical_path="Alexandria/Jobs/eth.md",
    ).route_detail()

    assert detail["error_code"] == "VERIFIED_UPSERT_RECOVERY_REQUIRED"
    assert detail["retryable"] is False
    assert detail["mutation_performed"] is False
    assert detail["safe_next_action"]
    assert detail["unsafe_action_warning"]
