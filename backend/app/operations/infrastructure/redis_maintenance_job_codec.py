"""Typed Redis response normalization for maintenance jobs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from app.operations.application.maintenance_job_queue import (
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    BatchNoteWriteJobItem,
    BatchNoteWriteJobResult,
    EmbeddingReindexJobResult,
    MaintenanceDeadLetterEntry,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue
from app.shared.types.redis_types import RedisResponse


class MaintenanceStatusFields(TypedDict, total=False):
    """Normalized Redis hash fields for one maintenance job."""

    job_id: str
    kind: str
    status: str
    requested_by: str
    source_id: str
    limit: str
    force: str
    attempts: str
    submitted_at: str
    started_at: str
    finished_at: str
    stream_id: str
    result_json: str
    error_summary: str


class MaintenanceDeadLetterFields(TypedDict, total=False):
    """Normalized Redis dead-letter stream fields for one terminal failure."""

    job_id: str
    kind: str
    attempts: str
    failed_at: str
    error_summary: str
    source_stream_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class EnqueueScriptResult:
    """Normalized atomic enqueue script response."""

    state: str
    value: str
    stream_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RedisStreamDelivery:
    """Minimal decoded Redis Streams delivery."""

    stream_id: str
    job_id: str


def decode_enqueue_result(raw: RedisResponse) -> EnqueueScriptResult:
    """Decode the three-value Lua enqueue response.

    Args:
        raw: Typed recursive Redis response returned by the enqueue script.

    Returns:
        Normalized enqueue state, identifier, and stream identifier.
    """
    values = _sequence(raw, "enqueue response")
    if len(values) != 3:
        raise MaintenanceQueueUnavailableError(
            "Redis maintenance enqueue returned an invalid response"
        )
    return EnqueueScriptResult(
        state=_text(values[0], "enqueue state"),
        value=_text(values[1], "enqueue value"),
        stream_id=_text(values[2], "enqueue stream id"),
    )


def decode_job_snapshot(raw: RedisResponse) -> MaintenanceJobSnapshot | None:
    """Decode one Redis status hash into an immutable domain snapshot.

    Args:
        raw: Typed Redis hash response loaded for one maintenance job.

    Returns:
        Immutable job snapshot, or None when the Redis hash is empty.
    """
    fields = _status_fields(raw)
    if not fields:
        return None
    result_json = fields.get("result_json", "")
    return MaintenanceJobSnapshot(
        job_id=_required(fields.get("job_id"), "job_id"),
        kind=MaintenanceJobKind(_required(fields.get("kind"), "kind")),
        status=MaintenanceJobStatus(_required(fields.get("status"), "status")),
        requested_by=_required(fields.get("requested_by"), "requested_by"),
        source_id=_required(fields.get("source_id"), "source_id"),
        limit=_integer(_required(fields.get("limit"), "limit"), "limit"),
        force=_required(fields.get("force"), "force") == "1",
        attempts=_integer(
            _required(fields.get("attempts"), "attempts"),
            "attempts",
        ),
        submitted_at=_datetime(
            _required(fields.get("submitted_at"), "submitted_at"),
            "submitted_at",
        ),
        started_at=_optional_datetime(fields.get("started_at"), "started_at"),
        finished_at=_optional_datetime(fields.get("finished_at"), "finished_at"),
        stream_id=_nonblank(fields.get("stream_id")),
        error_summary=_nonblank(fields.get("error_summary")),
        result=decode_job_result(fields.get("kind"), result_json)
        if result_json
        else None,
    )


def decode_job_result(
    kind: str | None, payload: bytes | str
) -> EmbeddingReindexJobResult | BatchNoteWriteJobResult:
    """Decode a persisted job result according to the job kind.

    Args:
        kind: Job kind recorded on the status hash.
        payload: Persisted JSON bytes or text from the Redis status hash.

    Returns:
        The kind-specific validated job result.

    Raises:
        MaintenanceQueueUnavailableError: When the kind is unknown.
    """
    if kind == MaintenanceJobKind.BATCH_NOTE_WRITE.value:
        return decode_batch_note_write_result(payload)
    if kind == MaintenanceJobKind.EMBEDDING_REINDEX.value:
        return decode_embedding_result(payload)
    raise MaintenanceQueueUnavailableError(
        "Redis maintenance job result kind is unknown"
    )


def encode_batch_note_write_result(result: BatchNoteWriteJobResult) -> bytes:
    """Serialize a bounded batch note write result for the status hash.

    Args:
        result: Immutable batch note write result.

    Returns:
        UTF-8 JSON bytes encoded by the shared orjson boundary.
    """
    payload: JSONObject = {
        "succeeded": result.succeeded,
        "conflicted": result.conflicted,
        "failed": result.failed,
        "items": [
            {
                "path": item.path,
                "status": item.status,
                "content_hash": item.content_hash,
                "current_content_hash": item.current_content_hash,
            }
            for item in result.items
        ],
    }
    return dumps_json(payload)


def decode_batch_note_write_result(payload: bytes | str) -> BatchNoteWriteJobResult:
    """Validate and decode a persisted batch note write result.

    Args:
        payload: Persisted JSON bytes or text from the Redis status hash.

    Returns:
        Validated immutable batch note write result.
    """
    decoded = loads_json(payload)
    if not isinstance(decoded, dict):
        raise MaintenanceQueueUnavailableError(
            "Redis maintenance result JSON must be an object"
        )
    items_raw = decoded.get("items", [])
    if not isinstance(items_raw, Sequence) or isinstance(items_raw, str | bytes):
        raise MaintenanceQueueUnavailableError(
            "Redis maintenance result items must be a sequence"
        )
    items: list[BatchNoteWriteJobItem] = []
    for item_raw in items_raw:
        if not isinstance(item_raw, dict):
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance result item must be an object"
            )
        items.append(
            BatchNoteWriteJobItem(
                path=_json_text(item_raw.get("path"), "path"),
                status=_json_text(item_raw.get("status"), "status"),
                content_hash=_json_optional_text(item_raw.get("content_hash")),
                current_content_hash=_json_optional_text(
                    item_raw.get("current_content_hash")
                ),
            )
        )
    return BatchNoteWriteJobResult(
        succeeded=_json_integer(decoded.get("succeeded"), "succeeded"),
        conflicted=_json_integer(decoded.get("conflicted"), "conflicted"),
        failed=_json_integer(decoded.get("failed"), "failed"),
        items=tuple(items),
    )


def encode_embedding_result(result: EmbeddingReindexJobResult) -> bytes:
    """Serialize a bounded result with the shared orjson codec.

    Args:
        result: Immutable embedding reindex result.

    Returns:
        UTF-8 JSON bytes encoded by the shared orjson boundary.
    """
    payload: JSONObject = {
        "scanned": result.scanned,
        "updated": result.updated,
        "skipped": result.skipped,
        "warnings": list(result.warnings),
    }
    return dumps_json(payload)


def decode_embedding_result(payload: bytes | str) -> EmbeddingReindexJobResult:
    """Validate and decode a persisted embedding result.

    Args:
        payload: Persisted JSON bytes or text from the Redis status hash.

    Returns:
        Validated immutable embedding reindex result.
    """
    decoded = loads_json(payload)
    if not isinstance(decoded, dict):
        raise MaintenanceQueueUnavailableError(
            "Redis maintenance result JSON must be an object"
        )
    scanned = _json_integer(decoded.get("scanned"), "scanned")
    updated = _json_integer(decoded.get("updated"), "updated")
    skipped = _json_integer(decoded.get("skipped"), "skipped")
    warnings_raw = decoded.get("warnings", [])
    if not isinstance(warnings_raw, Sequence) or isinstance(
        warnings_raw,
        str | bytes,
    ):
        raise MaintenanceQueueUnavailableError(
            "Redis maintenance result warnings must be a sequence"
        )
    warnings: list[str] = []
    for warning in warnings_raw:
        if not isinstance(warning, str):
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance result warning must be text"
            )
        warnings.append(warning)
    return EmbeddingReindexJobResult(
        scanned=scanned,
        updated=updated,
        skipped=skipped,
        warnings=tuple(warnings),
    )


def decode_pending_count(raw: RedisResponse) -> int:
    """Decode XPENDING summary output without retaining detail rows.

    Args:
        raw: Typed XPENDING summary response.

    Returns:
        Number of pending deliveries in the consumer group.
    """
    if isinstance(raw, dict):
        pending = raw.get("pending")
        if pending is None:
            pending = raw.get(b"pending")
        return _response_integer(pending, "pending")
    values = _sequence(raw, "pending summary")
    if not values:
        return 0
    return _response_integer(values[0], "pending")


def decode_consumer_count(raw: RedisResponse) -> int:
    """Decode XINFO CONSUMERS output by counting bounded records.

    Args:
        raw: Typed XINFO CONSUMERS response.

    Returns:
        Number of registered consumers.
    """
    return len(_sequence(raw, "consumer info"))


def decode_autoclaim_delivery(raw: RedisResponse) -> RedisStreamDelivery | None:
    """Decode the first XAUTOCLAIM entry, if present.

    Args:
        raw: Typed XAUTOCLAIM response.

    Returns:
        Decoded stream delivery, or None when no stale entry was claimed.
    """
    values = _sequence(raw, "autoclaim response")
    if len(values) < 2:
        return None
    entries = _sequence(values[1], "autoclaim entries")
    if not entries:
        return None
    return _delivery(entries[0])


def decode_readgroup_delivery(raw: RedisResponse) -> RedisStreamDelivery | None:
    """Decode the first XREADGROUP entry, if present.

    Args:
        raw: Typed XREADGROUP response.

    Returns:
        Decoded stream delivery, or None when no new entry was read.
    """
    streams = _sequence(raw, "readgroup response")
    if not streams:
        return None
    stream_record = _sequence(streams[0], "readgroup stream")
    if len(stream_record) < 2:
        return None
    entries = _sequence(stream_record[1], "readgroup entries")
    if not entries:
        return None
    return _delivery(entries[0])


def decode_dead_letter_entries(
    raw: RedisResponse,
) -> tuple[MaintenanceDeadLetterEntry, ...]:
    """Decode bounded XRANGE or XREVRANGE dead-letter stream output.

    Args:
        raw: Typed recursive Redis response holding stream entries.

    Returns:
        Immutable dead-letter entries in the order Redis returned them.
    """
    records = _sequence(raw, "dead-letter entries")
    entries: list[MaintenanceDeadLetterEntry] = []
    for record in records:
        values = _sequence(record, "dead-letter entry")
        if len(values) != 2:
            raise MaintenanceQueueUnavailableError("Redis dead-letter entry is invalid")
        fields = _dead_letter_fields(values[1])
        entries.append(
            MaintenanceDeadLetterEntry(
                entry_id=_text(values[0], "dead-letter entry id"),
                job_id=_required(fields.get("job_id"), "job_id"),
                kind=MaintenanceJobKind(_required(fields.get("kind"), "kind")),
                attempts=_integer(
                    _required(fields.get("attempts"), "attempts"),
                    "attempts",
                ),
                failed_at=_datetime(
                    _required(fields.get("failed_at"), "failed_at"),
                    "failed_at",
                ),
                error_summary=_nonblank(fields.get("error_summary")) or "",
                source_stream_id=_required(
                    fields.get("source_stream_id"),
                    "source_stream_id",
                ),
            )
        )
    return tuple(entries)


def decode_dead_letter_source_request(
    raw: RedisResponse,
) -> MaintenanceJobRequest | None:
    """Decode the maintenance request behind one dead-letter source entry.

    Args:
        raw: Typed recursive Redis response from the source stream range read.

    Returns:
        Replayed job request, or None when the source entry was trimmed.
    """
    records = _sequence(raw, "dead-letter source entries")
    if not records:
        return None
    values = _sequence(records[0], "dead-letter source entry")
    if len(values) != 2:
        raise MaintenanceQueueUnavailableError(
            "Redis dead-letter source entry is invalid"
        )
    fields = _status_fields(values[1])
    return MaintenanceJobRequest(
        kind=MaintenanceJobKind(_required(fields.get("kind"), "kind")),
        requested_by=_required(fields.get("requested_by"), "requested_by"),
        source_id=_required(fields.get("source_id"), "source_id"),
        limit=_integer(_required(fields.get("limit"), "limit"), "limit"),
        force=_required(fields.get("force"), "force") == "1",
    )


def response_integer(raw: RedisResponse, field: str) -> int:
    """Decode a Redis integer response.

    Args:
        raw: Typed Redis scalar or nested response to validate.
        field: Operator-facing field name used in validation errors.

    Returns:
        Validated integer response.
    """
    return _response_integer(raw, field)


def _delivery(raw: RedisResponse) -> RedisStreamDelivery:
    """Execute delivery.

    Args:
        raw: Raw used by this operation.

    Returns:
        RedisStreamDelivery result produced by delivery.
    """
    values = _sequence(raw, "stream delivery")
    if len(values) != 2:
        raise MaintenanceQueueUnavailableError(
            "Redis maintenance stream delivery is invalid"
        )
    fields = _status_fields(values[1])
    return RedisStreamDelivery(
        stream_id=_text(values[0], "stream id"),
        job_id=_required(fields.get("job_id"), "job_id"),
    )


def _status_fields(raw: RedisResponse) -> MaintenanceStatusFields:
    """Execute status fields.

    Args:
        raw: Raw used by this operation.

    Returns:
        MaintenanceStatusFields result produced by status fields.
    """
    if not isinstance(raw, dict):
        raise MaintenanceQueueUnavailableError(
            "Redis maintenance status must be a mapping"
        )
    normalized: MaintenanceStatusFields = {}
    for raw_key, raw_value in raw.items():
        key = _text(raw_key, "status key")
        value = _text(raw_value, key)
        if key == "job_id":
            normalized["job_id"] = value
        elif key == "kind":
            normalized["kind"] = value
        elif key == "status":
            normalized["status"] = value
        elif key == "requested_by":
            normalized["requested_by"] = value
        elif key == "source_id":
            normalized["source_id"] = value
        elif key == "limit":
            normalized["limit"] = value
        elif key == "force":
            normalized["force"] = value
        elif key == "attempts":
            normalized["attempts"] = value
        elif key == "submitted_at":
            normalized["submitted_at"] = value
        elif key == "started_at":
            normalized["started_at"] = value
        elif key == "finished_at":
            normalized["finished_at"] = value
        elif key == "stream_id":
            normalized["stream_id"] = value
        elif key == "result_json":
            normalized["result_json"] = value
        elif key == "error_summary":
            normalized["error_summary"] = value
    return normalized


def _dead_letter_fields(raw: RedisResponse) -> MaintenanceDeadLetterFields:
    """Normalize one dead-letter stream hash into known fields.

    Args:
        raw: Raw Redis hash response for one dead-letter entry.

    Returns:
        Normalized dead-letter field mapping.
    """
    if not isinstance(raw, dict):
        raise MaintenanceQueueUnavailableError(
            "Redis dead-letter entry must be a mapping"
        )
    normalized: MaintenanceDeadLetterFields = {}
    for raw_key, raw_value in raw.items():
        key = _text(raw_key, "dead-letter key")
        value = _text(raw_value, key)
        if key == "job_id":
            normalized["job_id"] = value
        elif key == "kind":
            normalized["kind"] = value
        elif key == "attempts":
            normalized["attempts"] = value
        elif key == "failed_at":
            normalized["failed_at"] = value
        elif key == "error_summary":
            normalized["error_summary"] = value
        elif key == "source_stream_id":
            normalized["source_stream_id"] = value
    return normalized


def _required(value: str | None, field: str) -> str:
    """Execute required.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        str result produced by required.
    """
    if value is None or not value:
        raise MaintenanceQueueUnavailableError(
            f"Redis maintenance status field is missing: {field}"
        )
    return value


def _sequence(raw: RedisResponse, field: str) -> Sequence[RedisResponse]:
    """Execute sequence.

    Args:
        raw: Raw used by this operation.
        field: Field used by this operation.

    Returns:
        Sequence[RedisResponse] result produced by sequence.
    """
    if isinstance(raw, list | tuple):
        return raw
    raise MaintenanceQueueUnavailableError(f"Redis {field} must be a sequence")


def _text(raw: RedisResponse, field: str) -> str:
    """Execute text.

    Args:
        raw: Raw used by this operation.
        field: Field used by this operation.

    Returns:
        str result produced by text.
    """
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MaintenanceQueueUnavailableError(
                f"Redis {field} is not valid UTF-8"
            ) from exc
    if isinstance(raw, str):
        return raw
    if isinstance(raw, int):
        return str(raw)
    raise MaintenanceQueueUnavailableError(f"Redis {field} must be text")


def _integer(value: str, field: str) -> int:
    """Execute integer.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        int result produced by integer.
    """
    try:
        return int(value)
    except ValueError as exc:
        raise MaintenanceQueueUnavailableError(
            f"Redis maintenance field must be an integer: {field}"
        ) from exc


def _response_integer(raw: RedisResponse, field: str) -> int:
    """Execute response integer.

    Args:
        raw: Raw used by this operation.
        field: Field used by this operation.

    Returns:
        int result produced by response integer.
    """
    if isinstance(raw, bool):
        raise MaintenanceQueueUnavailableError(f"Redis {field} must be an integer")
    if isinstance(raw, int):
        return raw
    return _integer(_text(raw, field), field)


def _json_integer(raw: JSONValue, field: str) -> int:
    """Execute json integer.

    Args:
        raw: Raw used by this operation.
        field: Field used by this operation.

    Returns:
        int result produced by json integer.
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise MaintenanceQueueUnavailableError(
            f"Redis maintenance result field must be an integer: {field}"
        )
    return raw


def _json_text(raw: JSONValue, field: str) -> str:
    """Execute json text.

    Args:
        raw: Raw used by this operation.
        field: Field used by this operation.

    Returns:
        str result produced by json text.
    """
    if not isinstance(raw, str):
        raise MaintenanceQueueUnavailableError(
            f"Redis maintenance result field must be text: {field}"
        )
    return raw


def _json_optional_text(raw: JSONValue) -> str | None:
    """Execute json optional text.

    Args:
        raw: Raw used by this operation.

    Returns:
        str | None result produced by json optional text.
    """
    if raw is None:
        return None
    return _json_text(raw, "optional text")


def _datetime(value: str, field: str) -> datetime:
    """Execute datetime.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        datetime result produced by datetime.
    """
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise MaintenanceQueueUnavailableError(
            f"Redis maintenance datetime is invalid: {field}"
        ) from exc


def _optional_datetime(value: str | None, field: str) -> datetime | None:
    """Execute optional datetime.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        datetime | None result produced by optional datetime.
    """
    normalized = _nonblank(value)
    if normalized is None:
        return None
    return _datetime(normalized, field)


def _nonblank(value: str | None) -> str | None:
    """Execute nonblank.

    Args:
        value: Value being processed.

    Returns:
        str | None result produced by nonblank.
    """
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
