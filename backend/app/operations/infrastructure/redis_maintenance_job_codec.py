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
    EmbeddingReindexJobResult,
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
        result=decode_embedding_result(result_json) if result_json else None,
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
