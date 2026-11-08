"""Lenient decoders for legacy nested maintenance DLQ archive records."""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterEntry,
    MaintenanceJobAttempt,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.types.extra_types import JSONValue

from .archive_fields import (
    archive_datetime_or_none,
    archive_integer,
    archive_string,
    archive_string_or_none,
)


def entry_from_archive(archive: dict[str, JSONValue]) -> MaintenanceDeadLetterEntry:
    """Decode the required dead-letter entry while retaining legacy defaults."""
    return MaintenanceDeadLetterEntry(
        entry_id=archive_string(archive.get("entry_id"), ""),
        job_id=archive_string(archive.get("job_id"), ""),
        kind=MaintenanceJobKind(
            archive_string(
                archive.get("kind"),
                MaintenanceJobKind.EMBEDDING_REINDEX.value,
            )
        ),
        attempts=archive_integer(archive.get("attempts")),
        failed_at=archive_datetime_or_none(archive.get("failed_at"))
        or datetime.now(UTC),
        error_summary=archive_string(archive.get("error_summary"), ""),
        source_stream_id=archive_string(archive.get("source_stream_id"), ""),
        lifecycle="RETIRED",
        attempt_history=attempts_from_archive(archive.get("attempt_history")),
    )


def attempts_from_archive(value: JSONValue) -> tuple[MaintenanceJobAttempt, ...]:
    """Decode only valid timestamped entries from a legacy attempt sequence."""
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    attempts: list[MaintenanceJobAttempt] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        occurred_at = archive_datetime_or_none(item.get("occurred_at"))
        status = item.get("status")
        if occurred_at is None or not isinstance(status, str):
            continue
        attempts.append(
            MaintenanceJobAttempt(
                attempt=archive_integer(item.get("attempt")),
                status=status,
                occurred_at=occurred_at,
                error_summary=archive_string_or_none(item.get("error_summary")),
            )
        )
    return tuple(attempts)


def request_from_archive(value: JSONValue) -> MaintenanceJobRequest | None:
    """Decode a valid archived source request, ignoring malformed legacy rows."""
    if not isinstance(value, dict):
        return None
    force = value.get("force")
    try:
        return MaintenanceJobRequest(
            kind=MaintenanceJobKind(archive_string(value.get("kind"), "")),
            requested_by=archive_string(value.get("requested_by"), ""),
            source_id=archive_string(value.get("source_id"), ""),
            limit=archive_integer(value.get("limit")),
            force=force if isinstance(force, bool) else False,
        )
    except TypeError, ValueError:
        return None


def job_from_archive(value: JSONValue) -> MaintenanceJobSnapshot | None:
    """Decode a valid archived job snapshot, ignoring malformed legacy rows."""
    if not isinstance(value, dict):
        return None
    force = value.get("force")
    try:
        return MaintenanceJobSnapshot(
            job_id=archive_string(value.get("job_id"), ""),
            kind=MaintenanceJobKind(archive_string(value.get("kind"), "")),
            status=MaintenanceJobStatus(archive_string(value.get("status"), "")),
            requested_by=archive_string(value.get("requested_by"), ""),
            source_id=archive_string(value.get("source_id"), ""),
            limit=archive_integer(value.get("limit")),
            force=force if isinstance(force, bool) else False,
            attempts=archive_integer(value.get("attempts")),
            submitted_at=archive_datetime_or_none(value.get("submitted_at"))
            or datetime.now(UTC),
            started_at=archive_datetime_or_none(value.get("started_at")),
            finished_at=archive_datetime_or_none(value.get("finished_at")),
            stream_id=archive_string_or_none(value.get("stream_id")),
            error_summary=archive_string_or_none(value.get("error_summary")),
        )
    except TypeError, ValueError:
        return None
