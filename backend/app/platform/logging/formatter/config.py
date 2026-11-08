"""JSON logging configuration module for backend services."""

from __future__ import annotations

import logging

from app.platform.config.app_config import AppConfig
from app.platform.logging.formatter.payload import (
    build_log_payload,
    flatten_log_payload,
    should_include_error_stack,
)
from app.platform.schemas.logging_schema import JsonLogServiceContext
from app.shared.serialization.orjson_codec import dumps_json


class JsonFormatter(logging.Formatter):
    """Formatter that converts log records into machine-readable JSON."""

    def __init__(
        self,
        service_context: JsonLogServiceContext,
        include_error_stack: bool,
    ) -> None:
        """Initialize a JSON formatter instance.

        Args:
            service_context: See function signature.
            include_error_stack: See function signature.

        Returns:
            None.
        """
        super().__init__()
        self._service_context = service_context
        self._include_error_stack = include_error_stack

    def format(self, record: logging.LogRecord) -> str:
        """Encode a log record as a JSON string.

        Args:
            record: See function signature.

        Returns:
            Return value.
        """
        payload = build_log_payload(
            record=record,
            service_context=self._service_context,
            include_error_stack=self._include_error_stack,
        )
        encoded_payload = dumps_json(flatten_log_payload(payload)).decode("utf-8")
        return encoded_payload


def configure_logging(app_config: AppConfig) -> None:
    """Configure root logging with a JSON stream handler.

    This function directly inspects and normalizes handler state so repeated calls
    do not register duplicate handlers and existing JSON handlers use current
    application metadata and policy.

    Args:
        app_config: Application configuration values.

    Returns:
        None.
    """
    level_name = app_config.app_log_level.upper()
    log_level = logging.getLevelNamesMapping().get(level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    if log_level == logging.DEBUG:
        client_log_level = logging.DEBUG
    else:
        client_log_level = max(log_level, logging.WARNING)
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(client_log_level)

    service_context = JsonLogServiceContext(
        service=app_config.app_name,
        env=app_config.app_env,
        version=app_config.app_version,
    )
    formatter = JsonFormatter(
        service_context=service_context,
        include_error_stack=should_include_error_stack(service_context.env),
    )
    has_json_stream_handler = False
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and isinstance(
            handler.formatter, JsonFormatter
        ):
            handler.setFormatter(formatter)
            has_json_stream_handler = True

    if not has_json_stream_handler:
        for existing_handler in root_logger.handlers[:]:
            root_logger.removeHandler(existing_handler)
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(logger_name)
        for existing_handler in uvicorn_logger.handlers[:]:
            uvicorn_logger.removeHandler(existing_handler)
        uvicorn_logger.propagate = True

    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    for existing_handler in uvicorn_access_logger.handlers[:]:
        uvicorn_access_logger.removeHandler(existing_handler)
    uvicorn_access_logger.propagate = False
    uvicorn_access_logger.disabled = True
