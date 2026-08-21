"""Pydantic payload models for structured JSON logging.

This module defines the internal contract for log events that are emitted to
stdout and can later be mapped to OpenTelemetry. Payloads are split by role so
no single model becomes overloaded.
"""

from __future__ import annotations

from typing import Annotated

from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_dict_default,
)
from app.shared.types.extra_types import JSONObject
from pydantic import ConfigDict, StrictInt, StrictStr


class JsonLoggingModel(StrictSchemaModel):
    """Base class for structured logging models.

    Purpose:
        Ensures all logging payload models share the same Pydantic policy:
        ``extra="forbid"`` blocks unknown fields, and ``frozen=True`` prevents
        mutation after creation.

        ``strict=True`` is a safety net across all models, preventing implicit
        coercion of values like numeric strings. ``StrictStr`` and ``StrictInt``
        clearly document identifier and numeric intentions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class JsonLogServiceContext(JsonLoggingModel):
    """Logging context containing service identification.

    Purpose:
        Captures which service/environment/version emitted the log, which can be
        mapped later to OpenTelemetry resource attributes.
    """

    service: StrictStr
    env: StrictStr
    version: StrictStr


class JsonLogTraceContext(JsonLoggingModel):
    """Logging context containing request and trace identifiers."""

    request_id: StrictStr | None
    correlation_id: StrictStr | None
    trace_id: StrictStr | None


class JsonLogHttpContext(JsonLoggingModel):
    """Logging context containing HTTP request/response details."""

    method: StrictStr | None
    path: StrictStr | None
    status_code: StrictInt | None


class JsonLogError(JsonLoggingModel):
    """Logging payload segment for exception information."""

    type: StrictStr | None
    message: StrictStr | None
    stack: StrictStr


class JsonLogPayload(JsonLoggingModel):
    """Full structured JSON log event payload."""

    ts: StrictStr
    level: StrictStr
    logger: StrictStr
    event: StrictStr
    msg: StrictStr
    func: StrictStr | None
    duration_ms: float | None
    attributes: Annotated[
        JSONObject, described_field("Attributes for this JSON log payload.")
    ] = schema_dict_default()
    service: JsonLogServiceContext
    trace: JsonLogTraceContext
    http: JsonLogHttpContext
    error: JsonLogError | None
