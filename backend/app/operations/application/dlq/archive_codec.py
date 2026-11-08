"""Encoding and lenient reading for maintenance DLQ retirement archives."""

from datetime import UTC, datetime

from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterInspection,
    MaintenanceDeadLetterRetireResult,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterOutcomeClass,
    MaintenanceDeadLetterRetirementClassification,
)
from app.shared.serialization.model_codec import schema_payload
from app.shared.types.extra_types import JSONObject, JSONValue

from .archive_fields import (
    archive_datetime_or_none,
    archive_string,
    archive_string_or_none,
    archive_string_tuple,
)
from .archive_records import (
    entry_from_archive,
    job_from_archive,
    request_from_archive,
)
from .archive_schemas import (
    ARCHIVE_KIND,
    ArchivedAttemptSchema,
    ArchivedJobSchema,
    ArchivedRequestSchema,
    MaintenanceDlqArchiveSchema,
)


class ArchiveCodec:
    """Own the strict writer and legacy-tolerant DLQ archive reader."""

    def encode(
        self,
        inspection: MaintenanceDeadLetterInspection,
        archive_id: str,
        reason: str,
        classification: MaintenanceDeadLetterRetirementClassification,
        retired_by: str,
        retired_at: datetime,
    ) -> JSONObject:
        """Build every persisted field through the complete strict archive schema."""
        entry = inspection.entry
        job = inspection.original_job
        request = inspection.source_request
        archive = MaintenanceDlqArchiveSchema(
            archive_kind=ARCHIVE_KIND,
            archive_id=archive_id,
            entry_id=entry.entry_id,
            job_id=entry.job_id,
            kind=entry.kind.value,
            attempts=entry.attempts,
            failed_at=entry.failed_at.isoformat(),
            error_summary=entry.error_summary,
            source_stream_id=entry.source_stream_id,
            attempt_history=[
                ArchivedAttemptSchema(
                    attempt=item.attempt,
                    status=item.status,
                    occurred_at=item.occurred_at.isoformat(),
                    error_summary=item.error_summary,
                )
                for item in entry.attempt_history
            ],
            source_identity=inspection.source_identity,
            source_request=(
                None
                if request is None
                else ArchivedRequestSchema(
                    kind=request.kind.value,
                    requested_by=request.requested_by,
                    source_id=request.source_id,
                    limit=request.limit,
                    force=request.force,
                )
            ),
            source_payload=inspection.source_payload,
            original_job=(
                None
                if job is None
                else ArchivedJobSchema(
                    job_id=job.job_id,
                    kind=job.kind.value,
                    status=job.status.value,
                    requested_by=job.requested_by,
                    source_id=job.source_id,
                    limit=job.limit,
                    force=job.force,
                    attempts=job.attempts,
                    submitted_at=job.submitted_at.isoformat(),
                    started_at=(
                        None if job.started_at is None else job.started_at.isoformat()
                    ),
                    finished_at=(
                        None if job.finished_at is None else job.finished_at.isoformat()
                    ),
                    stream_id=job.stream_id,
                    error_summary=job.error_summary,
                )
            ),
            idempotency_keys=list(inspection.idempotency_keys),
            effect_identities=list(inspection.effect_identities),
            retryable=inspection.retryable,
            outcome_class=inspection.outcome_class.value,
            recommended_action=inspection.recommended_action,
            error_history=list(inspection.error_history),
            retirement_reason=reason,
            retirement_classification=classification.value,
            retired_by=retired_by,
            retired_at=retired_at.isoformat(),
        )
        return schema_payload(archive)

    def decode_inspection(
        self, archive: dict[str, JSONValue], archive_id: str
    ) -> MaintenanceDeadLetterInspection:
        """Decode an archive without rejecting historical partial records."""
        entry = entry_from_archive(archive)
        job = job_from_archive(archive.get("original_job"))
        request = request_from_archive(archive.get("source_request"))
        outcome_value = archive_string(
            archive.get("outcome_class"),
            MaintenanceDeadLetterOutcomeClass.UNKNOWN_OUTCOME.value,
        )
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
        source_payload = archive.get("source_payload")
        return MaintenanceDeadLetterInspection(
            entry=entry,
            original_job=job,
            source_request=request,
            source_payload=(
                source_payload if isinstance(source_payload, dict) else None
            ),
            idempotency_keys=archive_string_tuple(archive.get("idempotency_keys")),
            effect_identities=archive_string_tuple(archive.get("effect_identities")),
            source_identity=archive_string(
                archive.get("source_identity"), "unavailable"
            ),
            retryable=False,
            outcome_class=outcome_class,
            recommended_action="already_retired",
            error_history=archive_string_tuple(archive.get("error_history")),
            retired=True,
            archive_id=archive_id,
            retirement_reason=archive_string_or_none(archive.get("retirement_reason")),
            retirement_classification=classification,
            retired_by=archive_string_or_none(archive.get("retired_by")),
            retired_at=archive_datetime_or_none(archive.get("retired_at")),
        )

    def decode_retirement(
        self, archive: dict[str, JSONValue], archive_id: str
    ) -> MaintenanceDeadLetterRetireResult:
        """Decode the retirement result with its historical timestamp fallback."""
        classification_raw = archive_string(
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
        retired_at = archive_datetime_or_none(
            archive.get("retired_at")
        ) or datetime.now(UTC)
        return MaintenanceDeadLetterRetireResult(
            entry_id=archive_string(archive.get("entry_id"), ""),
            job_id=archive_string(archive.get("job_id"), ""),
            archive_id=archive_id,
            retired_by=archive_string(archive.get("retired_by"), ""),
            retired_at=retired_at,
            reason=archive_string(archive.get("retirement_reason"), ""),
            classification=classification,
            retired=True,
        )
