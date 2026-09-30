"""Bounded inspect, retry, reconcile, and retire operations for maintenance DLQ."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

from app.obsidian.application.service.notes.obsidian_note_mutation_receipts import (
    note_mutation_identity,
)
from app.obsidian.domain.contracts.obsidian_batch_contracts import (
    BatchValidationError,
    BatchWriteOperation,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    ObsidianMutationOutcome,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianFrontmatterMode,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
)
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.operations.application.maintenance_job_queue import (
    MaintenanceDeadLetterNotFoundError,
    MaintenanceDeadLetterNotRetryableError,
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterContext,
    MaintenanceDeadLetterEntry,
    MaintenanceDeadLetterInspection,
    MaintenanceDeadLetterReconcileItem,
    MaintenanceDeadLetterReconcileResult,
    MaintenanceDeadLetterRetireResult,
    MaintenanceDeadLetterRetryResult,
    MaintenanceJobAttempt,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterOutcomeClass,
    MaintenanceDeadLetterRetirementClassification,
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.types.extra_types import JSONValue

PayloadReader = Callable[[str], Awaitable[dict[str, JSONValue] | None]]
ArchiveWriter = Callable[[str, dict[str, JSONValue]], Awaitable[bool]]
ArchiveReader = Callable[[str], Awaitable[dict[str, JSONValue] | None]]
NoteOutcomeReader = Callable[[str], Awaitable[ObsidianMutationOutcome]]
BatchIdentity = Callable[[BatchWriteOperation], tuple[str, str]]

_ARCHIVE_KIND = "maintenance_dlq_retirement"


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
        self._payload_reader = payload_reader
        self._archive_writer = archive_writer
        self._archive_reader = archive_reader
        self._note_outcome_reader = note_outcome_reader
        self._batch_identity = batch_identity or batch_operation_identity

    async def inspect(self, entry_id: str) -> MaintenanceDeadLetterInspection:
        """Read exact live or archived evidence without mutating state."""
        normalized_entry_id = _entry_id(entry_id)
        context = await self._queue.get_dead_letter(normalized_entry_id)
        if context is not None:
            return await self._inspect_context(context)
        archive_id = self.archive_id(normalized_entry_id)
        archive = await self._read_archive(archive_id)
        if archive is None:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        return _inspection_from_archive(archive, archive_id)

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
        if self._batch_identity is None or self._note_outcome_reader is None:
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
                idempotency_key, effect_identity = self._batch_identity(operation)
            except (BatchValidationError, TypeError, ValueError):
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
            return _retire_result_from_archive(archive, archive_id)
        if context is None:
            raise MaintenanceDeadLetterNotFoundError("dead-letter entry was not found")
        reserved = await self._queue.reserve_dead_letter_retirement(normalized_entry_id)
        if archive is None:
            inspection = await self._inspect_context(reserved)
            archive_body = _archive_body(
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

    async def _inspect_context(
        self, context: MaintenanceDeadLetterContext
    ) -> MaintenanceDeadLetterInspection:
        entry = context.entry
        job = context.original_job
        source_request = context.source_request
        source_identity = _source_identity(source_request, job)
        payload: dict[str, JSONValue] | None = None
        if (
            source_request is not None
            and source_request.kind is MaintenanceJobKind.BATCH_NOTE_WRITE
            and self._payload_reader is not None
        ):
            payload = await self._payload_reader(source_request.source_id)
        idempotency_keys, effect_identities = _batch_effect_identities(
            payload,
            self._batch_identity,
        )
        if (
            source_request is not None
            and source_request.kind is not MaintenanceJobKind.BATCH_NOTE_WRITE
        ):
            idempotency_keys = (source_identity,)
            effect_identities = (source_identity,)
        if job is None:
            return _inspection(
                context,
                payload,
                idempotency_keys=idempotency_keys,
                effect_identities=effect_identities,
                source_identity=source_identity,
                outcome_class=MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME,
                retryable=False,
                recommended_action="reconcile_missing_job",
            )
        if entry.lifecycle.startswith("RETRIED:"):
            return _inspection(
                context,
                payload,
                idempotency_keys=idempotency_keys,
                effect_identities=effect_identities,
                source_identity=source_identity,
                outcome_class=(
                    MaintenanceDeadLetterOutcomeClass.OBSOLETE
                    if job.status is MaintenanceJobStatus.SUCCEEDED
                    else MaintenanceDeadLetterOutcomeClass.NON_RETRYABLE
                ),
                retryable=False,
                recommended_action="observe_original_job",
            )
        if job.status is MaintenanceJobStatus.SUCCEEDED:
            return _inspection(
                context,
                payload,
                idempotency_keys=idempotency_keys,
                effect_identities=effect_identities,
                source_identity=source_identity,
                outcome_class=MaintenanceDeadLetterOutcomeClass.OBSOLETE,
                retryable=False,
                recommended_action="retire_obsolete_entry",
            )
        if job.status is not MaintenanceJobStatus.FAILED:
            return _inspection(
                context,
                payload,
                idempotency_keys=idempotency_keys,
                effect_identities=effect_identities,
                source_identity=source_identity,
                outcome_class=MaintenanceDeadLetterOutcomeClass.NON_RETRYABLE,
                retryable=False,
                recommended_action="observe_active_job",
            )
        if source_request is None:
            return _inspection(
                context,
                payload,
                idempotency_keys=idempotency_keys,
                effect_identities=effect_identities,
                source_identity=source_identity,
                outcome_class=MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME,
                retryable=False,
                recommended_action="retain_and_reconcile_source",
            )
        if source_request.kind is MaintenanceJobKind.BATCH_NOTE_WRITE:
            if payload is None:
                return _inspection(
                    context,
                    payload,
                    idempotency_keys=idempotency_keys,
                    effect_identities=effect_identities,
                    source_identity=source_identity,
                    outcome_class=MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME,
                    retryable=False,
                    recommended_action="retain_missing_payload",
                )
            if not _valid_batch_payload(payload):
                return _inspection(
                    context,
                    payload,
                    idempotency_keys=idempotency_keys,
                    effect_identities=effect_identities,
                    source_identity=source_identity,
                    outcome_class=MaintenanceDeadLetterOutcomeClass.NON_RETRYABLE,
                    retryable=False,
                    recommended_action="retire_invalid_source",
                )
            return _inspection(
                context,
                payload,
                idempotency_keys=idempotency_keys,
                effect_identities=effect_identities,
                source_identity=source_identity,
                outcome_class=MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME,
                retryable=False,
                recommended_action="reconcile_before_retry",
            )
        return _inspection(
            context,
            payload,
            idempotency_keys=idempotency_keys,
            effect_identities=effect_identities,
            source_identity=source_identity,
            outcome_class=MaintenanceDeadLetterOutcomeClass.DEFINITIVE_FAILURE,
            retryable=True,
            recommended_action="retry_same_identity",
        )

    async def _read_archive(self, archive_id: str) -> dict[str, JSONValue] | None:
        if self._archive_reader is None:
            return None
        return await self._archive_reader(archive_id)


def _inspection(
    context: MaintenanceDeadLetterContext,
    payload: dict[str, JSONValue] | None,
    *,
    idempotency_keys: tuple[str, ...] = (),
    effect_identities: tuple[str, ...] = (),
    source_identity: str,
    outcome_class: MaintenanceDeadLetterOutcomeClass,
    retryable: bool,
    recommended_action: str,
) -> MaintenanceDeadLetterInspection:
    entry = context.entry
    errors = tuple(
        item.error_summary for item in entry.attempt_history if item.error_summary
    )
    if entry.error_summary and entry.error_summary not in errors:
        errors += (entry.error_summary,)
    return MaintenanceDeadLetterInspection(
        entry=entry,
        original_job=context.original_job,
        source_request=context.source_request,
        source_payload=payload,
        idempotency_keys=idempotency_keys,
        effect_identities=effect_identities,
        source_identity=source_identity,
        retryable=retryable,
        outcome_class=outcome_class,
        recommended_action=recommended_action,
        error_history=errors,
    )


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


def _source_identity(
    request: MaintenanceJobRequest | None,
    job: MaintenanceJobSnapshot | None,
) -> str:
    source = request or (
        MaintenanceJobRequest(
            kind=job.kind,
            requested_by=job.requested_by,
            source_id=job.source_id,
            limit=job.limit,
            force=job.force,
        )
        if job is not None
        else None
    )
    if source is None:
        return "unavailable"
    return ":".join(
        (
            source.kind.value,
            source.source_id,
            str(source.limit),
            "1" if source.force else "0",
        )
    )


def _valid_batch_payload(payload: dict[str, JSONValue]) -> bool:
    operations = payload.get("operations")
    if not isinstance(operations, Sequence) or isinstance(operations, str | bytes):
        return False
    try:
        for operation in operations:
            BatchWriteOperation.from_payload(operation)
    except (BatchValidationError, TypeError, ValueError):
        return False
    return True


def _batch_effect_identities(
    payload: dict[str, JSONValue] | None,
    identity: BatchIdentity,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if payload is None:
        return (), ()
    operations = payload.get("operations")
    if not isinstance(operations, Sequence) or isinstance(operations, str | bytes):
        return (), ()
    keys: list[str] = []
    identities: list[str] = []
    for raw_operation in operations:
        try:
            operation = BatchWriteOperation.from_payload(raw_operation)
            key, effect = identity(operation)
        except (BatchValidationError, TypeError, ValueError):
            return (), ()
        keys.append(key)
        identities.append(effect)
    return tuple(keys), tuple(identities)


def batch_operation_identity(operation: BatchWriteOperation) -> tuple[str, str]:
    """Reuse the ordinary note-write identity for one batch operation."""
    payload = ObsidianSaveNote(
        title=operation.title,
        body=operation.body,
        alexandria_type=AlexandriaNoteType.CONTEXT,
        note_id=operation.note_id,
        relative_path=operation.relative_path,
        frontmatter=dict(operation.frontmatter),
        expected_content_hash=operation.expected_content_hash,
    )
    command = ObsidianWriteNote(
        note=payload,
        write_mode=ObsidianWriteMode.UPSERT,
        match_by=ObsidianWriteMatchBy.PATH,
        frontmatter_mode=ObsidianFrontmatterMode.MERGE,
    )
    return note_mutation_identity(payload, command)


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


def _archive_body(
    inspection: MaintenanceDeadLetterInspection,
    *,
    archive_id: str,
    reason: str,
    classification: MaintenanceDeadLetterRetirementClassification,
    retired_by: str,
    retired_at: datetime,
) -> dict[str, JSONValue]:
    entry = inspection.entry
    job = inspection.original_job
    request = inspection.source_request
    return {
        "archive_kind": _ARCHIVE_KIND,
        "archive_id": archive_id,
        "entry_id": entry.entry_id,
        "job_id": entry.job_id,
        "kind": entry.kind.value,
        "attempts": entry.attempts,
        "failed_at": entry.failed_at.isoformat(),
        "error_summary": entry.error_summary,
        "source_stream_id": entry.source_stream_id,
        "attempt_history": [
            {
                "attempt": item.attempt,
                "status": item.status,
                "occurred_at": item.occurred_at.isoformat(),
                "error_summary": item.error_summary,
            }
            for item in entry.attempt_history
        ],
        "source_identity": inspection.source_identity,
        "source_request": None
        if request is None
        else {
            "kind": request.kind.value,
            "requested_by": request.requested_by,
            "source_id": request.source_id,
            "limit": request.limit,
            "force": request.force,
        },
        "source_payload": inspection.source_payload,
        "original_job": None if job is None else _job_payload(job),
        "idempotency_keys": list(inspection.idempotency_keys),
        "effect_identities": list(inspection.effect_identities),
        "retryable": inspection.retryable,
        "outcome_class": inspection.outcome_class.value,
        "recommended_action": inspection.recommended_action,
        "error_history": list(inspection.error_history),
        "retirement_reason": reason,
        "retirement_classification": classification.value,
        "retired_by": retired_by,
        "retired_at": retired_at.isoformat(),
    }


def _job_payload(job: MaintenanceJobSnapshot) -> dict[str, JSONValue]:
    return {
        "job_id": job.job_id,
        "kind": job.kind.value,
        "status": job.status.value,
        "requested_by": job.requested_by,
        "source_id": job.source_id,
        "limit": job.limit,
        "force": job.force,
        "attempts": job.attempts,
        "submitted_at": job.submitted_at.isoformat(),
        "started_at": None if job.started_at is None else job.started_at.isoformat(),
        "finished_at": None if job.finished_at is None else job.finished_at.isoformat(),
        "stream_id": job.stream_id,
        "error_summary": job.error_summary,
    }


def _inspection_from_archive(
    archive: dict[str, JSONValue], archive_id: str
) -> MaintenanceDeadLetterInspection:
    entry = _entry_from_archive(archive)
    job = _job_from_archive(archive.get("original_job"))
    request = _request_from_archive(archive.get("source_request"))
    outcome_value = _string(archive.get("outcome_class"), "UNKNOWN_OUTCOME")
    try:
        outcome_class = MaintenanceDeadLetterOutcomeClass(outcome_value)
    except ValueError:
        outcome_class = MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME
    classification_value = archive.get("retirement_classification")
    classification = None
    if isinstance(classification_value, str):
        try:
            classification = MaintenanceDeadLetterRetirementClassification(
                classification_value
            )
        except ValueError:
            classification = None
    retired_at = _datetime_or_none(archive.get("retired_at"))
    return MaintenanceDeadLetterInspection(
        entry=entry,
        original_job=job,
        source_request=request,
        source_payload=_json_object_or_none(archive.get("source_payload")),
        idempotency_keys=_string_tuple(archive.get("idempotency_keys")),
        effect_identities=_string_tuple(archive.get("effect_identities")),
        source_identity=_string(archive.get("source_identity"), "unavailable"),
        retryable=False,
        outcome_class=outcome_class,
        recommended_action="already_retired",
        error_history=_string_tuple(archive.get("error_history")),
        retired=True,
        archive_id=archive_id,
        retirement_reason=_string_or_none(archive.get("retirement_reason")),
        retirement_classification=classification,
        retired_by=_string_or_none(archive.get("retired_by")),
        retired_at=retired_at,
    )


def _retire_result_from_archive(
    archive: dict[str, JSONValue], archive_id: str
) -> MaintenanceDeadLetterRetireResult:
    classification_raw = _string(
        archive.get("retirement_classification"),
        MaintenanceDeadLetterRetirementClassification.HISTORICAL_RESIDUAL.value,
    )
    try:
        classification = MaintenanceDeadLetterRetirementClassification(
            classification_raw
        )
    except ValueError:
        classification = (
            MaintenanceDeadLetterRetirementClassification.HISTORICAL_RESIDUAL
        )
    retired_at = _datetime_or_none(archive.get("retired_at")) or datetime.now(UTC)
    return MaintenanceDeadLetterRetireResult(
        entry_id=_string(archive.get("entry_id"), ""),
        job_id=_string(archive.get("job_id"), ""),
        archive_id=archive_id,
        retired_by=_string(archive.get("retired_by"), ""),
        retired_at=retired_at,
        reason=_string(archive.get("retirement_reason"), ""),
        classification=classification,
        retired=True,
    )


def _entry_from_archive(
    archive: dict[str, JSONValue],
) -> MaintenanceDeadLetterEntry:
    return MaintenanceDeadLetterEntry(
        entry_id=_string(archive.get("entry_id"), ""),
        job_id=_string(archive.get("job_id"), ""),
        kind=MaintenanceJobKind(
            _string(archive.get("kind"), MaintenanceJobKind.EMBEDDING_REINDEX.value)
        ),
        attempts=_integer(archive.get("attempts")),
        failed_at=_datetime_or_none(archive.get("failed_at")) or datetime.now(UTC),
        error_summary=_string(archive.get("error_summary"), ""),
        source_stream_id=_string(archive.get("source_stream_id"), ""),
        lifecycle="RETIRED",
        attempt_history=_attempts_from_archive(archive.get("attempt_history")),
    )


def _attempts_from_archive(
    value: JSONValue,
) -> tuple[MaintenanceJobAttempt, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    attempts: list[MaintenanceJobAttempt] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        occurred_at = _datetime_or_none(item.get("occurred_at"))
        status = item.get("status")
        if occurred_at is None or not isinstance(status, str):
            continue
        attempts.append(
            MaintenanceJobAttempt(
                attempt=_integer(item.get("attempt")),
                status=status,
                occurred_at=occurred_at,
                error_summary=_string_or_none(item.get("error_summary")),
            )
        )
    return tuple(attempts)


def _request_from_archive(value: JSONValue) -> MaintenanceJobRequest | None:
    if not isinstance(value, dict):
        return None
    try:
        return MaintenanceJobRequest(
            kind=MaintenanceJobKind(_string(value.get("kind"), "")),
            requested_by=_string(value.get("requested_by"), ""),
            source_id=_string(value.get("source_id"), ""),
            limit=_integer(value.get("limit")),
            force=_boolean(value.get("force")),
        )
    except (TypeError, ValueError):
        return None


def _job_from_archive(value: JSONValue) -> MaintenanceJobSnapshot | None:
    if not isinstance(value, dict):
        return None
    try:
        return MaintenanceJobSnapshot(
            job_id=_string(value.get("job_id"), ""),
            kind=MaintenanceJobKind(_string(value.get("kind"), "")),
            status=MaintenanceJobStatus(_string(value.get("status"), "")),
            requested_by=_string(value.get("requested_by"), ""),
            source_id=_string(value.get("source_id"), ""),
            limit=_integer(value.get("limit")),
            force=_boolean(value.get("force")),
            attempts=_integer(value.get("attempts")),
            submitted_at=_datetime_or_none(value.get("submitted_at"))
            or datetime.now(UTC),
            started_at=_datetime_or_none(value.get("started_at")),
            finished_at=_datetime_or_none(value.get("finished_at")),
            stream_id=_string_or_none(value.get("stream_id")),
            error_summary=_string_or_none(value.get("error_summary")),
        )
    except (TypeError, ValueError):
        return None


def _json_object_or_none(value: JSONValue) -> dict[str, JSONValue] | None:
    return value if isinstance(value, dict) else None


def _string_tuple(value: JSONValue) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _string(value: JSONValue, default: str) -> str:
    return value if isinstance(value, str) else default


def _string_or_none(value: JSONValue) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value: JSONValue) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _boolean(value: JSONValue) -> bool:
    return value if isinstance(value, bool) else False


def _datetime_or_none(value: JSONValue) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None
