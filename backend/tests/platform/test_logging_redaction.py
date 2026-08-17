"""Structured logging redaction regression tests."""

from __future__ import annotations

import logging
import sys

from app.platform.logging.formatter.config import JsonFormatter
from app.platform.schemas.logging_schema import JsonLogServiceContext
from app.shared.serialization.orjson_codec import loads_json


def _formatter() -> JsonFormatter:
    """Return a formatter with stack traces enabled for redaction coverage."""
    return JsonFormatter(
        service_context=JsonLogServiceContext(
            service="heterarchy-alexandria",
            env="local",
            version="test",
        ),
        include_error_stack=True,
    )


def test_json_formatter_redacts_secret_values_in_messages_and_exceptions() -> None:
    """JSON formatter should not serialize secret values from log text."""
    logger_name = "tests.platform.logging_redaction"
    logger = logging.getLogger(logger_name)

    try:
        raise RuntimeError(
            "provider failed api_key=do-not-log-api-key "
            "oauth_access_token=do-not-log-token "
            "oauth_refresh_token=do-not-log-refresh-token "
            "device_code=do-not-log-device-code user_code=do-not-log-user-code "
            "Authorization: Bearer do-not-log-bearer"
        )
    except RuntimeError:
        record = logger.makeRecord(
            logger_name,
            logging.ERROR,
            __file__,
            1,
            "request failed password=do-not-log-password",
            args=(),
            exc_info=sys.exc_info(),
        )

    encoded = _formatter().format(record)
    payload = loads_json(encoded)

    assert "do-not-log-api-key" not in encoded
    assert "do-not-log-token" not in encoded
    assert "do-not-log-refresh-token" not in encoded
    assert "do-not-log-device-code" not in encoded
    assert "do-not-log-user-code" not in encoded
    assert "do-not-log-bearer" not in encoded
    assert "do-not-log-password" not in encoded
    assert payload["msg"] == "request failed password=<redacted>"
    assert payload["error"]["message"] == (
        "provider failed api_key=<redacted> oauth_access_token=<redacted> "
        "oauth_refresh_token=<redacted> device_code=<redacted> "
        "user_code=<redacted> "
        "Authorization: Bearer <redacted>"
    )
    assert "api_key=<redacted>" in payload["error"]["stack"]


def test_json_formatter_preserves_and_redacts_structured_attributes() -> None:
    """Structured attributes should remain queryable without leaking credentials."""
    logger_name = "tests.platform.logging_attributes"
    logger = logging.getLogger(logger_name)
    record = logger.makeRecord(
        logger_name,
        logging.INFO,
        __file__,
        1,
        "reconciliation completed",
        args=(),
        exc_info=None,
        extra={
            "event": "memory_reconciliation_apply_completed",
            "duration_ms": 12.5,
            "attributes": {
                "plan_id": "plan-1",
                "status": "APPLIED",
                "nested": {
                    "authorization": "Bearer do-not-log-bearer",
                    "api_key": "api_key=do-not-log-api-key",
                },
            },
        },
    )

    encoded = _formatter().format(record)
    payload = loads_json(encoded)

    assert payload["event"] == "memory_reconciliation_apply_completed"
    assert payload["duration_ms"] == 12.5
    assert payload["attributes"]["plan_id"] == "plan-1"
    assert payload["attributes"]["status"] == "APPLIED"
    assert payload["attributes"]["nested"]["authorization"] == ("Bearer <redacted>")
    assert payload["attributes"]["nested"]["api_key"] == "api_key=<redacted>"
    assert "do-not-log" not in encoded
