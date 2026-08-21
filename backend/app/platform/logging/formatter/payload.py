"""Pure payload construction and shaping for JSON log records."""

from __future__ import annotations

import logging
import traceback
from datetime import UTC, datetime
from types import TracebackType

from app.platform.schemas.logging_schema import (
    JsonLogError,
    JsonLogHttpContext,
    JsonLogPayload,
    JsonLogServiceContext,
    JsonLogTraceContext,
)
from app.shared.serialization.model_codec import model_to_dict
from app.shared.types.extra_types import JSONObject
from app.shared.utils.logging import (
    LogRecordExtraReader,
    redact_sensitive_json_object,
    redact_sensitive_text,
)


def should_include_error_stack(app_env: str) -> bool:
    """Decide whether error stack traces are included based on environment.

    Args:
        app_env: Application environment name.

    Returns:
        Whether stack traces should be emitted.
    """
    should_include_stack = app_env.lower() in {"local", "stage", "prod"}
    return should_include_stack


def format_error_stack(
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    exc_tb: TracebackType | None,
    include_stack: bool,
) -> str:
    """Convert an exception traceback to a redacted JSON logging string.

    Args:
        exc_type: Exception type from ``LogRecord.exc_info``.
        exc_value: Exception value from ``LogRecord.exc_info``.
        exc_tb: Traceback from ``LogRecord.exc_info``.
        include_stack: Whether stack traces are enabled for the environment.

    Returns:
        Redacted stack text, or an empty string when disabled.
    """
    if not include_stack:
        return ""
    stack_text = redact_sensitive_text(
        "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    )
    formatted_stack = stack_text or ""
    return formatted_stack


def build_error_payload(
    record: logging.LogRecord,
    include_stack: bool,
) -> JsonLogError | None:
    """Build a structured error payload from a log record.

    Args:
        record: Python logging record.
        include_stack: Whether stack traces are enabled for the environment.

    Returns:
        Structured error payload when exception info is present.
    """
    if not record.exc_info:
        return None

    exc_type, exc_value, exc_tb = record.exc_info
    exc_type_name: str | None = None if exc_type is None else exc_type.__name__
    exc_message: str | None = None
    if exc_value is not None:
        exc_message = redact_sensitive_text(str(exc_value))

    error_payload = JsonLogError(
        type=exc_type_name,
        message=exc_message,
        stack=format_error_stack(
            exc_type=exc_type,
            exc_value=exc_value,
            exc_tb=exc_tb,
            include_stack=include_stack,
        ),
    )
    return error_payload


def build_trace_context(extra_reader: LogRecordExtraReader) -> JsonLogTraceContext:
    """Build trace context payload from a log record.

    Args:
        extra_reader: Typed reader for structured logging extra fields.

    Returns:
        Structured trace context.
    """
    request_id = extra_reader.string("request_id")
    trace_context = JsonLogTraceContext(
        request_id=request_id,
        correlation_id=extra_reader.string(
            "correlation_id",
            default=request_id,
        ),
        trace_id=extra_reader.string("trace_id"),
    )
    return trace_context


def build_http_context(extra_reader: LogRecordExtraReader) -> JsonLogHttpContext:
    """Build HTTP context payload from a log record.

    Args:
        extra_reader: Typed reader for structured logging extra fields.

    Returns:
        Structured HTTP context.
    """
    http_context = JsonLogHttpContext(
        method=extra_reader.string("http_method"),
        path=extra_reader.string("path"),
        status_code=extra_reader.int_value("status_code"),
    )
    return http_context


def build_log_payload(
    record: logging.LogRecord,
    service_context: JsonLogServiceContext,
    include_error_stack: bool,
) -> JsonLogPayload:
    """Create a validated structured Pydantic payload for one log record.

    Args:
        record: Python logging record.
        service_context: Service context to attach to the log event.
        include_error_stack: Whether stack traces are enabled for the environment.

    Returns:
        Validated structured log payload.
    """
    extra_reader = LogRecordExtraReader(record)
    event_name = extra_reader.required_string(
        "event",
        default=record.name,
    )
    log_payload = JsonLogPayload(
        ts=datetime.now(UTC).isoformat(timespec="milliseconds"),
        level=record.levelname,
        logger=record.name,
        event=event_name,
        msg=redact_sensitive_text(record.getMessage()) or "",
        func=extra_reader.string("func", default=record.funcName),
        duration_ms=extra_reader.float_value("duration_ms"),
        attributes=redact_sensitive_json_object(
            extra_reader.json_object("attributes", default={}) or {}
        ),
        service=service_context,
        trace=build_trace_context(extra_reader),
        http=build_http_context(extra_reader),
        error=build_error_payload(record=record, include_stack=include_error_stack),
    )
    return log_payload


def flatten_log_payload(payload: JsonLogPayload) -> JSONObject:
    """Flatten nested payload models into a flat dictionary for log output.

    Args:
        payload: Structured log payload.

    Returns:
        JSON-compatible flat log object.
    """
    payload_dict = model_to_dict(payload)
    service = payload_dict.pop("service", {})
    trace = payload_dict.pop("trace", {})
    http = payload_dict.pop("http", {})

    if not isinstance(service, dict):
        service = {}
    if not isinstance(trace, dict):
        trace = {}
    if not isinstance(http, dict):
        http = {}

    flattened_payload: JSONObject = {
        **payload_dict,
        **service,
        **trace,
        "http_method": http.get("method"),
        "path": http.get("path"),
        "status_code": http.get("status_code"),
    }
    return flattened_payload
