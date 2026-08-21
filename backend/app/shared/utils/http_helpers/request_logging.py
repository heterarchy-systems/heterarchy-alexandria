"""Structured HTTP request logging helpers."""

from __future__ import annotations

import logging

from fastapi.responses import Response

HEALTHCHECK_PATHS = {"/health/live", "/health/ready", "/health/heartbeat"}
RequestLogExtra = dict[str, str | int | float | None]


def should_skip_request_log(path: str, status_code: int) -> bool:
    """Decide whether to skip request logging.

    Args:
        path: Request path without query string.
        status_code: HTTP response status code.

    Returns:
        True when the request should be skipped (healthcheck handling rule).
    """
    skip_request_log = path in HEALTHCHECK_PATHS and (
        status_code < 500 or status_code == 503
    )
    return skip_request_log


def request_log_metadata(
    response: Response,
) -> tuple[int, str, str]:
    """Determine request log level and event name based on response status.

    Args:
        response: FastAPI response whose status code determines log severity.

    Returns:
        Logging level, structured event name, and human-readable message.
    """
    if response.status_code >= 500:
        metadata = (
            logging.ERROR,
            "request_server_error",
            "request completed with server error",
        )
        return metadata

    metadata = logging.INFO, "request_completed", "request completed"
    return metadata


class RequestLogContext:
    """Structured request logging context with shared request metadata."""

    __slots__ = (
        "_duration_ms",
        "_func",
        "_http_method",
        "_path",
        "_request_id",
        "_status_code",
        "_trace_id",
    )

    def __init__(
        self,
        request_id: str,
        trace_id: str,
        http_method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        func: str | None,
    ) -> None:
        """Initialize shared metadata for one request log record.

        Args:
            request_id: Request/correlation identifier.
            trace_id: Trace identifier.
            http_method: HTTP method.
            path: Request path without query string.
            status_code: Response status code.
            duration_ms: Request duration in milliseconds.
            func: Fully-qualified endpoint function name when available.
        """
        self._request_id = request_id
        self._trace_id = trace_id
        self._http_method = http_method
        self._path = path
        self._status_code = status_code
        self._duration_ms = duration_ms
        self._func = func

    def extra(self, event: str) -> RequestLogExtra:
        """Build the structured log extra payload for a request event.

        Args:
            event: Structured log event name.

        Returns:
            Structured logging extra fields.
        """
        return {
            "event": event,
            "request_id": self._request_id,
            "correlation_id": self._request_id,
            "trace_id": self._trace_id,
            "http_method": self._http_method,
            "path": self._path,
            "status_code": self._status_code,
            "duration_ms": self._duration_ms,
            "func": self._func,
        }

    def log_outcome(
        self,
        logger: logging.Logger,
        level: int,
        message: str,
        event: str,
    ) -> None:
        """Log a completed request outcome as a structured record.

        Args:
            logger: Logger used for request events.
            level: Logging level.
            message: Log message.
            event: Structured log event name.
        """
        logger.log(level, message, extra=self.extra(event=event))

    def log_exception(
        self,
        logger: logging.Logger,
        message: str,
        event: str,
    ) -> None:
        """Log a request failure with an attached exception.

        Args:
            logger: Logger used for request events.
            message: Log message.
            event: Structured log event name.
        """
        logger.exception(message, extra=self.extra(event=event))
