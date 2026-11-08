"""Request logging policy and logger-level regression tests."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from io import StringIO

import pytest
from fastapi.responses import Response
from tests.config_test_data import app_config_values

from app.platform.config.app_config import AppConfig
from app.platform.logging.formatter import config as logging_config
from app.platform.logging.formatter.payload import should_include_error_stack
from app.platform.schemas.logging_schema import JsonLogServiceContext
from app.shared.utils.http_helpers.request_logging import (
    request_log_metadata,
    should_skip_request_log,
)


@pytest.fixture
def preserve_logging_state() -> Iterator[None]:
    """Restore process-wide logger configuration after each test."""
    logger_names = (
        None,
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "httpx",
        "httpcore",
    )
    loggers = {name: logging.getLogger(name) for name in logger_names}
    previous_state = {
        logger: (
            logger.level,
            tuple(logger.handlers),
            logger.propagate,
            logger.disabled,
        )
        for logger in loggers.values()
    }
    previous_formatters = {
        handler: handler.formatter
        for logger in loggers.values()
        for handler in logger.handlers
    }
    yield
    for logger, (level, handlers, propagate, disabled) in previous_state.items():
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        for handler in handlers:
            logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = propagate
        logger.disabled = disabled
    for handler, formatter in previous_formatters.items():
        handler.setFormatter(formatter)


@pytest.mark.parametrize(
    ("status_code", "expected_level", "expected_event"),
    [
        (200, logging.DEBUG, "request_completed"),
        (302, logging.DEBUG, "request_completed"),
        (400, logging.INFO, "request_completed"),
        (401, logging.INFO, "request_completed"),
        (403, logging.INFO, "request_completed"),
        (500, logging.ERROR, "request_server_error"),
        (503, logging.ERROR, "request_server_error"),
    ],
)
def test_request_log_metadata_preserves_failures_and_debugs_successes(
    status_code: int,
    expected_level: int,
    expected_event: str,
) -> None:
    """Successful requests are debug-level while client/server failures stay visible."""
    level, event, _ = request_log_metadata(Response(status_code=status_code))

    assert (level, event) == (expected_level, expected_event)


@pytest.mark.parametrize(
    ("path", "status_code", "expected_skip"),
    [
        ("/health/live", 200, True),
        ("/health/ready", 302, True),
        ("/health/heartbeat", 399, True),
        ("/health/live", 400, False),
        ("/health/ready", 401, False),
        ("/health/heartbeat", 403, False),
        ("/health/live", 503, False),
        ("/other", 200, False),
    ],
)
def test_health_request_logging_suppresses_only_successes(
    path: str,
    status_code: int,
    expected_skip: bool,
) -> None:
    """Health successes stay silent and failed health checks remain observable."""
    assert should_skip_request_log(path, status_code) is expected_skip


def test_configure_logging_preserves_root_level_and_controls_http_loggers(
    preserve_logging_state: None,
) -> None:
    """HTTP client noise is muted at INFO and restored for explicit DEBUG."""
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.addHandler(logging.StreamHandler(StringIO()))
        logger.propagate = False
        logger.disabled = False

    logging_config.configure_logging(
        AppConfig(_env_file=None, **app_config_values(app_log_level="INFO"))
    )

    assert logging.getLogger().level == logging.INFO
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        assert logger.handlers == []
        assert logger.propagate is (logger_name != "uvicorn.access")
    assert logging.getLogger("uvicorn.access").disabled is True

    logging_config.configure_logging(
        AppConfig(_env_file=None, **app_config_values(app_log_level="ERROR"))
    )

    assert logging.getLogger().level == logging.ERROR
    for logger_name in ("httpx", "httpcore"):
        client_logger = logging.getLogger(logger_name)
        assert client_logger.level == logging.ERROR
        assert client_logger.isEnabledFor(logging.WARNING) is False
        assert client_logger.isEnabledFor(logging.ERROR) is True

    logging_config.configure_logging(
        AppConfig(_env_file=None, **app_config_values(app_log_level="CRITICAL"))
    )
    for logger_name in ("httpx", "httpcore"):
        client_logger = logging.getLogger(logger_name)
        assert client_logger.isEnabledFor(logging.ERROR) is False
        assert client_logger.isEnabledFor(logging.CRITICAL) is True

    logging_config.configure_logging(
        AppConfig(_env_file=None, **app_config_values(app_log_level="DEBUG"))
    )

    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("httpx").level == logging.DEBUG
    assert logging.getLogger("httpcore").level == logging.DEBUG


def test_configure_logging_normalizes_root_handlers_to_json(
    preserve_logging_state: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The first configuration replaces non-project handlers with JSON output."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    root_logger.addHandler(logging.StreamHandler(StringIO()))

    logging_config.configure_logging(
        AppConfig(
            _env_file=None,
            **app_config_values(
                app_name="normalized-service",
                app_env="local",
                app_version="normalized-version",
            ),
        )
    )
    root_logger.warning("normalized root output", extra={"event": "normalized"})

    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip())
    assert len(root_logger.handlers) == 1
    assert payload["service"] == "normalized-service"
    assert payload["event"] == "normalized"


def test_configure_logging_refreshes_existing_json_handlers_from_app_config(
    preserve_logging_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every existing project stream handler uses each supplied config policy."""
    monkeypatch.setenv("SERVICE_APP_NAME", "environment-service")
    monkeypatch.setenv("SERVICE_APP_ENV", "stage")
    monkeypatch.setenv("SERVICE_APP_VERSION", "environment-version")
    monkeypatch.setenv("SERVICE_APP_LOG_LEVEL", "CRITICAL")

    streams = (StringIO(), StringIO())
    stale_context = JsonLogServiceContext(
        service="stale-service",
        env="test",
        version="stale-version",
    )
    handlers = tuple(logging.StreamHandler(stream) for stream in streams)
    for handler in handlers:
        handler.setFormatter(
            logging_config.JsonFormatter(
                service_context=stale_context,
                include_error_stack=False,
            )
        )

    root_logger = logging.getLogger()
    for existing_handler in root_logger.handlers[:]:
        root_logger.removeHandler(existing_handler)
    for handler in handlers:
        root_logger.addHandler(handler)
    original_handlers = tuple(root_logger.handlers)

    local_config = AppConfig(
        _env_file=None,
        **app_config_values(
            app_name="explicit-local-service",
            app_env="local",
            app_version="local-version",
            app_log_level="DEBUG",
        ),
    )
    logging_config.configure_logging(local_config)
    try:
        raise RuntimeError("local failure")
    except RuntimeError:
        root_logger.exception("local logging policy", extra={"event": "local"})
    local_payloads = tuple(
        json.loads(stream.getvalue().splitlines()[-1]) for stream in streams
    )

    prod_config = AppConfig(
        _env_file=None,
        **app_config_values(
            app_name="explicit-prod-service",
            app_env="prod",
            app_version="prod-version",
            app_log_level="ERROR",
        ),
    )
    logging_config.configure_logging(prod_config)
    try:
        raise RuntimeError("production failure")
    except RuntimeError:
        root_logger.exception("production logging policy", extra={"event": "prod"})
    prod_payloads = tuple(
        json.loads(stream.getvalue().splitlines()[-1]) for stream in streams
    )

    logging_config.configure_logging(prod_config)
    try:
        raise RuntimeError("repeated production failure")
    except RuntimeError:
        root_logger.exception("repeated production logging policy")
    repeated_payloads = tuple(
        json.loads(stream.getvalue().splitlines()[-1]) for stream in streams
    )

    assert len(root_logger.handlers) == len(original_handlers) == 2
    assert all(
        current is original
        for current, original in zip(
            root_logger.handlers,
            original_handlers,
            strict=True,
        )
    )
    assert all(
        (payload["service"], payload["env"], payload["version"])
        == ("explicit-local-service", "local", "local-version")
        for payload in local_payloads
    )
    assert all(
        bool(payload["error"]["stack"])
        is should_include_error_stack(local_config.app_env)
        for payload in local_payloads
    )
    assert all(
        (payload["service"], payload["env"], payload["version"])
        == ("explicit-prod-service", "prod", "prod-version")
        for payload in prod_payloads + repeated_payloads
    )
    assert all(
        bool(payload["error"]["stack"])
        is should_include_error_stack(prod_config.app_env)
        for payload in prod_payloads
    )
