"""Read live DLQ evidence and derive same-note identities without mutation."""

from collections.abc import Sequence

from app.obsidian.domain.contracts.obsidian_batch_contracts import (
    BatchValidationError,
    BatchWriteOperation,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterContext,
    MaintenanceDeadLetterInspection,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterOutcomeClass,
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.types.extra_types import JSONValue

from .batch_identity import batch_operation_identity
from .contracts import BatchIdentity, PayloadReader


class LiveInspection:
    """Own payload reads and identity derivation for live queue evidence."""

    def __init__(
        self,
        payload_reader: PayloadReader | None,
        batch_identity: BatchIdentity | None,
    ) -> None:
        """Bind the existing optional source reader and identity policy."""
        self._payload_reader = payload_reader
        self._batch_identity = batch_identity or batch_operation_identity

    async def inspect(
        self, context: MaintenanceDeadLetterContext
    ) -> MaintenanceDeadLetterInspection:
        """Inspect one live queue context using only source reads."""
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

    def identity_for(self, operation: BatchWriteOperation) -> tuple[str, str]:
        """Apply the same identity policy to one receipt reconciliation item."""
        return self._batch_identity(operation)


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
    except BatchValidationError, TypeError, ValueError:
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
        except BatchValidationError, TypeError, ValueError:
            return (), ()
        keys.append(key)
        identities.append(effect)
    return tuple(keys), tuple(identities)
