"""Bounded inspect, retry, reconcile, and retire operations for maintenance DLQ."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from app.obsidian.domain.contracts.obsidian_batch_contracts import (
    BatchValidationError,
    BatchWriteOperation,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    ObsidianMutationOutcome,
)
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.operations.application.dlq.archive_codec import ArchiveCodec
from app.operations.application.dlq.contracts import (
    ArchiveReader,
    ArchiveWriter,
    BatchIdentity,
    NoteOutcomeReader,
    PayloadReader,
)
from app.operations.application.dlq.live_inspection import LiveInspection
from app.operations.application.maintenance_job_queue import (
    MaintenanceDeadLetterNotFoundError,
    MaintenanceDeadLetterNotRetryableError,
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterInspection,
    MaintenanceDeadLetterReconcileItem,
    MaintenanceDeadLetterReconcileResult,
    MaintenanceDeadLetterRetireResult,
    MaintenanceDeadLetterRetryResult,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterOutcomeClass,
    MaintenanceDeadLetterRetirementClassification,
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.types.extra_types import JSONValue


class MaintenanceDeadLetterLifecycleService:
    """Apply evidence gates around the existing Redis queue and note receipts."""

    def __init__(
        self,
        queue: MaintenanceJobSubmitter,
        *,
        archive_namespace: str,
        payload_reader: PayloadReader | None = None,
        archive_writer: ArchiveWriter | None = None,
        archive_reader: ArchiveReader | None = None,
        note_outcome_reader: NoteOutcomeReader | None = None,
        batch_identity: BatchIdentity | None = None,
    ) -> None:
        """Initialize the bounded DLQ application service."""
        if not archive_namespace.strip():
            raise ValueError("archive_namespace must not be blank")
        self._queue = queue
        self._archive_namespace = archive_namespace.strip()
        self._archive_writer = archive_writer
        self._archive_reader = archive_reader
        self._note_outcome_reader = note_outcome_reader
        self._live_inspection = LiveInspection(payload_reader, batch_identity)
        self._archive_codec = ArchiveCodec()

    async def inspect(self, entry_id: str) -> MaintenanceDeadLetterInspection:
        """Read exact live or archived evidence without mutating state."""
        normalized_entry_id = _entry_id(entry_id)
        context = await self._queue.get_dead_letter(normalized_entry_id)
        if context is not None:
            return await self._live_inspection.inspect(context)
        archive_id = self.archive_id(normalized_entry_id)
        archive = await self._read_archive(archive_id)
        if archive is None:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        return self._archive_codec.decode_inspection(archive, archive_id)

    async def retry(
        self,
        entry_id: str,
        *,
        dry_run: bool,
        reason: str,
    ) -> MaintenanceDeadLetterRetryResult:
        """Preview or same-ID retry one evidence-approved terminal job."""
        normalized_reason = _reason(reason, "retry reason")
        inspection = await self.inspect(entry_id)
        retryable = inspection.retryable
        outcome_class = inspection.outcome_class
        if (
            inspection.entry.kind is MaintenanceJobKind.BATCH_NOTE_WRITE
            and not inspection.retired
        ):
            reconciliation = await self.reconcile(entry_id)
            retryable = reconciliation.retryable
            outcome_class = reconciliation.outcome_class
        if inspection.retired:
            return MaintenanceDeadLetterRetryResult(
                entry_id=inspection.entry.entry_id,
                job_id=inspection.entry.job_id,
                dry_run=dry_run,
                retryable=False,
                status=(
                    inspection.original_job.status
                    if inspection.original_job is not None
                    else None
                ),
                snapshot=inspection.original_job,
                reason=normalized_reason,
                outcome_class=outcome_class,
            )
        if not retryable:
            if (
                inspection.entry.lifecycle.startswith("RETRIED:")
                and inspection.original_job is not None
            ):
                return MaintenanceDeadLetterRetryResult(
                    entry_id=inspection.entry.entry_id,
                    job_id=inspection.entry.job_id,
                    dry_run=dry_run,
                    retryable=False,
                    status=inspection.original_job.status,
                    snapshot=inspection.original_job,
                    reason=normalized_reason,
                    outcome_class=outcome_class,
                )
            raise MaintenanceDeadLetterNotRetryableError(
                f"dead-letter outcome is {outcome_class.value}"
            )
        if dry_run:
            return MaintenanceDeadLetterRetryResult(
                entry_id=inspection.entry.entry_id,
                job_id=inspection.entry.job_id,
                dry_run=True,
                retryable=True,
                status=MaintenanceJobStatus.FAILED,
                snapshot=inspection.original_job,
                reason=normalized_reason,
                outcome_class=outcome_class,
            )
        snapshot = await self._queue.retry_dead_letter(
            inspection.entry.entry_id,
            normalized_reason,
        )
        return MaintenanceDeadLetterRetryResult(
            entry_id=inspection.entry.entry_id,
            job_id=inspection.entry.job_id,
            dry_run=False,
            retryable=True,
            status=snapshot.status,
            snapshot=snapshot,
            reason=normalized_reason,
            outcome_class=outcome_class,
        )

    async def reconcile(self, entry_id: str) -> MaintenanceDeadLetterReconcileResult:
        """Read per-item note receipts without mutating the queue or source."""
        inspection = await self.inspect(entry_id)
        if inspection.entry.kind is not MaintenanceJobKind.BATCH_NOTE_WRITE:
            return MaintenanceDeadLetterReconcileResult(
                entry_id=inspection.entry.entry_id,
                job_id=inspection.entry.job_id,
                outcome_class=inspection.outcome_class,
                retryable=inspection.retryable,
                recommended_action=inspection.recommended_action,
            )
        payload = inspection.source_payload
        if payload is None:
            return MaintenanceDeadLetterReconcileResult(
                entry_id=inspection.entry.entry_id,
                job_id=inspection.entry.job_id,
                outcome_class=MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME,
                retryable=False,
                recommended_action="retain_and_review_source",
                source_available=False,
            )
        raw_operations = payload.get("operations")
        if not isinstance(raw_operations, Sequence) or isinstance(
            raw_operations, str | bytes
        ):
            return MaintenanceDeadLetterReconcileResult(
                entry_id=inspection.entry.entry_id,
                job_id=inspection.entry.job_id,
                outcome_class=MaintenanceDeadLetterOutcomeClass.NON_RETRYABLE,
                retryable=False,
                recommended_action="retire_invalid_source",
                source_available=False,
            )
        if self._note_outcome_reader is None:
            return MaintenanceDeadLetterReconcileResult(
                entry_id=inspection.entry.entry_id,
                job_id=inspection.entry.job_id,
                outcome_class=MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME,
                retryable=False,
                recommended_action="wire_note_receipt_reader",
            )
        items: list[MaintenanceDeadLetterReconcileItem] = []
        has_unknown = False
        has_conflict = False
        has_pending = False
        for index, raw_operation in enumerate(raw_operations):
            try:
                operation = BatchWriteOperation.from_payload(raw_operation)
                idempotency_key, effect_identity = self._live_inspection.identity_for(
                    operation
                )
            except BatchValidationError, TypeError, ValueError:
                has_unknown = True
                items.append(
                    MaintenanceDeadLetterReconcileItem(
                        index=index,
                        idempotency_key="",
                        effect_identity="",
                        status="NON_RETRYABLE",
                        evidence=("source_operation_invalid",),
                    )
                )
                continue
            try:
                outcome = await self._note_outcome_reader(idempotency_key)
            except (OSError, RuntimeError, ValueError) as exc:
                has_unknown = True
                items.append(
                    MaintenanceDeadLetterReconcileItem(
                        index=index,
                        idempotency_key=idempotency_key,
                        effect_identity=effect_identity,
                        status="UNKNOWN",
                        evidence=("receipt_reader_failed", type(exc).__name__),
                    )
                )
                continue
            items.append(
                _reconcile_item(index, idempotency_key, effect_identity, outcome)
            )
            if outcome.status in {
                ObsidianMutationOutcomeStatus.UNKNOWN,
                ObsidianMutationOutcomeStatus.RECONCILIATION_REQUIRED,
            }:
                has_unknown = True
            elif outcome.status is ObsidianMutationOutcomeStatus.CONFLICTED:
                has_conflict = True
            elif outcome.status is ObsidianMutationOutcomeStatus.NOT_COMMITTED:
                has_pending = True
        if has_unknown:
            outcome_class = MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME
            retryable = False
            action = "reconcile_unknown_items"
        elif has_conflict:
            outcome_class = MaintenanceDeadLetterOutcomeClass.CONFLICT
            retryable = False
            action = "retire_conflicted_items"
        elif has_pending:
            outcome_class = MaintenanceDeadLetterOutcomeClass.DEFINITIVE_FAILURE
            retryable = True
            action = "retry_same_identity"
        else:
            outcome_class = MaintenanceDeadLetterOutcomeClass.OBSOLETE
            retryable = False
            action = "retire_already_applied"
        return MaintenanceDeadLetterReconcileResult(
            entry_id=inspection.entry.entry_id,
            job_id=inspection.entry.job_id,
            outcome_class=outcome_class,
            retryable=retryable,
            items=tuple(items),
            recommended_action=action,
        )

    async def retire(
        self,
        entry_id: str,
        *,
        reason: str,
        classification: MaintenanceDeadLetterRetirementClassification,
        retired_by: str,
    ) -> MaintenanceDeadLetterRetireResult:
        """Reserve, archive, and exactly clean one DLQ entry."""
        normalized_reason = _reason(reason, "retirement reason")
        actor = _reason(retired_by, "retired_by")
        if not isinstance(
            classification, MaintenanceDeadLetterRetirementClassification
        ):
            classification = MaintenanceDeadLetterRetirementClassification(
                classification
            )
        normalized_entry_id = _entry_id(entry_id)
        archive_id = self.archive_id(normalized_entry_id)
        archive = await self._read_archive(archive_id)
        context = await self._queue.get_dead_letter(normalized_entry_id)
        if archive is not None and context is None:
            return self._archive_codec.decode_retirement(archive, archive_id)
        if context is None:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        reserved = await self._queue.reserve_dead_letter_retirement(normalized_entry_id)
        if archive is None:
            inspection = await self._live_inspection.inspect(reserved)
            archive_body = self._archive_codec.encode(
                inspection,
                archive_id=archive_id,
                reason=normalized_reason,
                classification=classification,
                retired_by=actor,
                retired_at=datetime.now(UTC),
            )
            writer = self._archive_writer
            if writer is None:
                raise MaintenanceQueueUnavailableError(
                    "DLQ retirement archive writer is not configured"
                )
            await writer(archive_id, archive_body)
        try:
            await self._queue.finalize_dead_letter_retirement(
                normalized_entry_id,
                reserved.entry.source_stream_id,
                reserved.entry.job_id,
            )
        except MaintenanceQueueUnavailableError:
            return MaintenanceDeadLetterRetireResult(
                entry_id=normalized_entry_id,
                job_id=reserved.entry.job_id,
                archive_id=archive_id,
                retired_by=actor,
                retired_at=datetime.now(UTC),
                reason=normalized_reason,
                classification=classification,
                retired=False,
                pending_cleanup=True,
            )
        return MaintenanceDeadLetterRetireResult(
            entry_id=normalized_entry_id,
            job_id=reserved.entry.job_id,
            archive_id=archive_id,
            retired_by=actor,
            retired_at=datetime.now(UTC),
            reason=normalized_reason,
            classification=classification,
            retired=True,
        )

    def archive_id(self, entry_id: str) -> str:
        """Derive a stable UUID archive identity namespaced by DLQ stream."""
        return uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"alexandria:maintenance-dlq:{self._archive_namespace}:{entry_id}",
        ).hex

    async def _read_archive(self, archive_id: str) -> dict[str, JSONValue] | None:
        if self._archive_reader is None:
            return None
        return await self._archive_reader(archive_id)


def _entry_id(entry_id: str) -> str:
    normalized = entry_id.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("dead-letter entry_id must contain 1..128 characters")
    return normalized


def _reason(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ValueError(f"{field} must contain 1..500 characters")
    return normalized


def _reconcile_item(
    index: int,
    idempotency_key: str,
    effect_identity: str,
    outcome: ObsidianMutationOutcome,
) -> MaintenanceDeadLetterReconcileItem:
    return MaintenanceDeadLetterReconcileItem(
        index=index,
        idempotency_key=idempotency_key,
        effect_identity=effect_identity,
        status=outcome.status.value,
        evidence=outcome.evidence,
        canonical_path=outcome.canonical_path,
        content_hash=outcome.content_hash,
    )
