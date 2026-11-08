"""Compatibility contracts for previously written maintenance DLQ archives."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio
import pytest
from tests.operations.test_maintenance_dlq_service import _context, _FakeQueue

from app.operations.application.maintenance_dlq_service import (
    MaintenanceDeadLetterLifecycleService,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterOutcomeClass,
    MaintenanceDeadLetterRetirementClassification,
)
from app.shared.types.extra_types import JSONValue


@pytest.mark.parametrize(
    ("source_request", "original_job"),
    [
        (
            {"kind": "unknown-request-kind"},
            {
                "job_id": "legacy-job-1",
                "kind": "embedding_reindex",
                "status": "unknown-job-status",
            },
        ),
        ({}, {}),
        ({"kind": None}, {"kind": "embedding_reindex"}),
    ],
)
def test_legacy_archive_inspection_and_retirement_stay_permissive(
    source_request: dict[str, JSONValue],
    original_job: dict[str, JSONValue],
) -> None:
    async def scenario() -> None:
        entry_id = "legacy-entry-1"
        failed_at = datetime(2026, 11, 6, 1, 2, 3, tzinfo=UTC)
        retired_at = datetime(2026, 11, 6, 4, 5, 6, tzinfo=UTC)
        archive: dict[str, JSONValue] = {
            "archive_kind": "legacy-v0",
            "archive_id": "stored-legacy-id",
            "entry_id": entry_id,
            "job_id": "legacy-job-1",
            "kind": "embedding_reindex",
            "attempts": True,
            "failed_at": failed_at.isoformat(),
            "error_summary": "legacy failure",
            "source_stream_id": "3-0",
            "attempt_history": [
                {
                    "attempt": 2,
                    "status": "FAILED",
                    "occurred_at": "not-a-timestamp",
                    "error_summary": "discarded bad timestamp",
                },
                "not-an-attempt-object",
            ],
            "source_identity": "legacy-source",
            "source_request": source_request,
            "source_payload": {
                "operations": [{"op": "upsert", "relative_path": "A.md"}],
                "requested_by": "legacy-agent",
            },
            "original_job": original_job,
            "idempotency_keys": ["key-one", 7, None, "key-two"],
            "effect_identities": ["effect-one", False, {"id": "effect-two"}],
            "retryable": True,
            "outcome_class": "future-outcome-class",
            "recommended_action": "retry-anyway",
            "error_history": ["earlier failure", 42, None, "terminal failure"],
            "retirement_reason": "historical retirement",
            "retirement_classification": "future-retirement-class",
            "retired_by": "previous operator",
            "retired_at": retired_at.isoformat(),
        }
        archive_reads: list[str] = []

        async def read_archive(archive_id: str) -> dict[str, JSONValue] | None:
            archive_reads.append(archive_id)
            return archive

        queue = _FakeQueue(_context())
        queue.context = None
        service = MaintenanceDeadLetterLifecycleService(
            queue,
            archive_namespace="dead",
            archive_reader=read_archive,
        )
        expected_archive_id = "9fbd797f1260500d806a95cf0434596c"

        inspection = await service.inspect(entry_id)
        retirement = await service.retire(
            entry_id,
            reason="ignored for an existing archive",
            classification=MaintenanceDeadLetterRetirementClassification.OBSOLETE,
            retired_by="ignored operator",
        )

        assert service.archive_id(entry_id) == expected_archive_id
        assert archive_reads == [expected_archive_id, expected_archive_id]
        assert inspection.archive_id == expected_archive_id
        assert inspection.entry.entry_id == entry_id
        assert inspection.entry.attempts == 0
        assert inspection.entry.failed_at == failed_at
        assert inspection.entry.attempt_history == ()
        assert inspection.original_job is None
        assert inspection.source_request is None
        assert inspection.source_payload == archive["source_payload"]
        assert inspection.idempotency_keys == ("key-one", "key-two")
        assert inspection.effect_identities == ("effect-one",)
        assert inspection.error_history == ("earlier failure", "terminal failure")
        assert (
            inspection.outcome_class
            is MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME
        )
        assert inspection.retryable is False
        assert inspection.recommended_action == "already_retired"
        assert inspection.retirement_reason == "historical retirement"
        assert inspection.retirement_classification is None
        assert inspection.retired_by == "previous operator"
        assert inspection.retired_at == retired_at

        assert retirement.entry_id == entry_id
        assert retirement.job_id == "legacy-job-1"
        assert retirement.archive_id == expected_archive_id
        assert retirement.retired_by == "previous operator"
        assert retirement.retired_at == retired_at
        assert retirement.reason == "historical retirement"
        assert (
            retirement.classification
            is MaintenanceDeadLetterRetirementClassification.HISTORICAL_RESIDUAL
        )
        assert retirement.retired is True
        assert queue.finalize_calls == []

    anyio.run(scenario)
