"""Focused maintenance dead-letter lifecycle regressions."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio
import pytest

from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    ObsidianMutationOutcome,
)
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.operations.application.maintenance_dlq_service import (
    MaintenanceDeadLetterLifecycleService,
)
from app.operations.application.maintenance_job_queue import (
    MaintenanceDeadLetterNotRetryableError,
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterContext,
    MaintenanceDeadLetterEntry,
    MaintenanceDeadLetterInspection,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterRetirementClassification,
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.types.extra_types import JSONValue


class _FakeQueue:
    def __init__(self, context: MaintenanceDeadLetterContext) -> None:
        self.context: MaintenanceDeadLetterContext | None = context
        self.retry_calls: list[tuple[str, str]] = []
        self.finalize_calls: list[tuple[str, str, str | None]] = []

    async def get_dead_letter(
        self, _entry_id: str
    ) -> MaintenanceDeadLetterContext | None:
        return self.context

    async def retry_dead_letter(
        self, entry_id: str, reason: str
    ) -> MaintenanceJobSnapshot:
        self.retry_calls.append((entry_id, reason))
        assert self.context is not None
        job = self.context.original_job
        assert job is not None
        queued = MaintenanceJobSnapshot(
            job_id=job.job_id,
            kind=job.kind,
            status=MaintenanceJobStatus.QUEUED,
            requested_by=job.requested_by,
            source_id=job.source_id,
            limit=job.limit,
            force=job.force,
            attempts=0,
            submitted_at=job.submitted_at,
            stream_id="9-0",
        )
        self.context = MaintenanceDeadLetterContext(
            entry=self.context.entry.__class__(
                entry_id=self.context.entry.entry_id,
                job_id=self.context.entry.job_id,
                kind=self.context.entry.kind,
                attempts=self.context.entry.attempts,
                failed_at=self.context.entry.failed_at,
                error_summary=self.context.entry.error_summary,
                source_stream_id=self.context.entry.source_stream_id,
                lifecycle=f"RETRIED:{job.job_id}",
                attempt_history=self.context.entry.attempt_history,
            ),
            original_job=queued,
            source_request=self.context.source_request,
        )
        return queued

    async def reserve_dead_letter_retirement(
        self, entry_id: str
    ) -> MaintenanceDeadLetterContext:
        assert self.context is not None
        self.context = MaintenanceDeadLetterContext(
            entry=self.context.entry.__class__(
                entry_id=self.context.entry.entry_id,
                job_id=self.context.entry.job_id,
                kind=self.context.entry.kind,
                attempts=self.context.entry.attempts,
                failed_at=self.context.entry.failed_at,
                error_summary=self.context.entry.error_summary,
                source_stream_id=self.context.entry.source_stream_id,
                lifecycle="RETIRING",
                attempt_history=self.context.entry.attempt_history,
            ),
            original_job=self.context.original_job,
            source_request=self.context.source_request,
        )
        return self.context

    async def finalize_dead_letter_retirement(
        self, entry_id: str, source_stream_id: str, job_id: str | None = None
    ) -> bool:
        self.finalize_calls.append((entry_id, source_stream_id, job_id))
        self.context = None
        return True


def _context(
    kind: MaintenanceJobKind = MaintenanceJobKind.EMBEDDING_REINDEX,
    *,
    payload_source: str = "source-1",
) -> MaintenanceDeadLetterContext:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    entry = MaintenanceDeadLetterEntry(
        entry_id="7-0",
        job_id="job-1",
        kind=kind,
        attempts=3,
        failed_at=now,
        error_summary="terminal failure",
        source_stream_id="3-0",
    )
    request = MaintenanceJobRequest(
        kind=kind,
        requested_by="operator",
        source_id=payload_source,
        limit=50,
        force=False,
    )
    job = MaintenanceJobSnapshot(
        job_id="job-1",
        kind=kind,
        status=MaintenanceJobStatus.FAILED,
        requested_by=request.requested_by,
        source_id=request.source_id,
        limit=request.limit,
        force=request.force,
        attempts=entry.attempts,
        submitted_at=now,
        finished_at=now,
        stream_id=entry.source_stream_id,
        error_summary=entry.error_summary,
    )
    return MaintenanceDeadLetterContext(
        entry=entry,
        original_job=job,
        source_request=request,
    )


def test_definitive_embedding_failure_supports_dry_run_and_same_id_retry() -> None:
    async def scenario() -> tuple[bool, MaintenanceJobSnapshot, list[tuple[str, str]]]:
        queue = _FakeQueue(_context())
        service = MaintenanceDeadLetterLifecycleService(
            queue, archive_namespace="alexandria:maintenance:dead:v1"
        )
        preview = await service.retry("7-0", dry_run=True, reason="operator review")
        result = await service.retry("7-0", dry_run=False, reason="operator review")
        assert result.snapshot is not None
        return preview.dry_run, result.snapshot, queue.retry_calls

    dry_run, snapshot, calls = anyio.run(scenario)
    assert dry_run is True
    assert snapshot.job_id == "job-1"
    assert snapshot.status is MaintenanceJobStatus.QUEUED
    assert calls == [("7-0", "operator review")]


def test_unknown_batch_outcome_blocks_blind_retry() -> None:
    async def scenario() -> None:
        queue = _FakeQueue(
            _context(MaintenanceJobKind.BATCH_NOTE_WRITE, payload_source="batch-1")
        )

        async def payload_reader(_source_id: str) -> dict[str, JSONValue]:
            return {
                "operations": [
                    {
                        "op": "upsert",
                        "title": "A",
                        "body": "# A",
                        "relative_path": "Alexandria/A.md",
                    }
                ]
            }

        async def unknown(_key: str) -> ObsidianMutationOutcome:
            return ObsidianMutationOutcome(
                operation="note_write",
                idempotency_key="unknown",
                status=ObsidianMutationOutcomeStatus.UNKNOWN,
                evidence=("readback_failed",),
            )

        service = MaintenanceDeadLetterLifecycleService(
            queue,
            archive_namespace="dead",
            payload_reader=payload_reader,
            note_outcome_reader=unknown,
        )
        with pytest.raises(MaintenanceDeadLetterNotRetryableError):
            await service.retry("7-0", dry_run=False, reason="retry")
        reconciled = await service.reconcile("7-0")
        assert reconciled.outcome_class.value == "UNKNOWN_OUTCOME"
        assert queue.retry_calls == []

    anyio.run(scenario)


def test_reconcile_preserves_already_committed_batch_item() -> None:
    async def scenario() -> tuple[str, bool, str]:
        queue = _FakeQueue(
            _context(MaintenanceJobKind.BATCH_NOTE_WRITE, payload_source="batch-1")
        )

        async def payload_reader(_source_id: str) -> dict[str, JSONValue]:
            return {
                "operations": [
                    {
                        "op": "upsert",
                        "title": "A",
                        "body": "# A",
                        "relative_path": "Alexandria/A.md",
                    }
                ]
            }

        async def committed(key: str) -> ObsidianMutationOutcome:
            return ObsidianMutationOutcome(
                operation="note_write",
                idempotency_key=key,
                status=ObsidianMutationOutcomeStatus.COMMITTED,
                evidence=("durable_checkpoint_readback_verified",),
            )

        service = MaintenanceDeadLetterLifecycleService(
            queue,
            archive_namespace="dead",
            payload_reader=payload_reader,
            note_outcome_reader=committed,
        )
        result = await service.reconcile("7-0")
        return result.outcome_class.value, result.retryable, result.items[0].status

    outcome, retryable, item_status = anyio.run(scenario)
    assert outcome == "OBSOLETE"
    assert retryable is False
    assert item_status == "COMMITTED"


def test_retire_archives_provenance_before_exact_cleanup_and_inspect_reads_archive() -> (
    None
):
    async def scenario() -> tuple[bool, str, MaintenanceDeadLetterInspection]:
        queue = _FakeQueue(_context())
        archives: dict[str, dict[str, object]] = {}

        async def write_archive(identity: str, body: dict[str, JSONValue]) -> bool:
            archives.setdefault(identity, body)
            return identity not in archives

        async def read_archive(identity: str) -> dict[str, JSONValue] | None:
            return archives.get(identity)

        service = MaintenanceDeadLetterLifecycleService(
            queue,
            archive_namespace="dead",
            archive_writer=write_archive,
            archive_reader=read_archive,
        )
        result = await service.retire(
            "7-0",
            reason="already reviewed",
            classification=MaintenanceDeadLetterRetirementClassification.NON_RETRYABLE,
            retired_by="operator",
        )
        inspected = await service.inspect("7-0")
        return result.retired, result.archive_id, inspected

    retired, archive_id, inspected = anyio.run(scenario)
    assert retired is True
    assert archive_id == inspected.archive_id
    assert inspected.retired is True
    assert inspected.retirement_reason == "already reviewed"


def test_redis_unavailable_is_not_treated_as_an_alternate_authority() -> None:
    class UnavailableQueue:
        async def get_dead_letter(self, _entry_id: str) -> None:
            raise MaintenanceQueueUnavailableError("redis down")

    async def scenario() -> None:
        service = MaintenanceDeadLetterLifecycleService(
            UnavailableQueue(), archive_namespace="dead"
        )
        with pytest.raises(MaintenanceQueueUnavailableError):
            await service.inspect("7-0")

    anyio.run(scenario)
