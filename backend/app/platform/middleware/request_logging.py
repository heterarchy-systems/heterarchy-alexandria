"""Middleware for JSON request logging."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import Response

from app.shared.serialization.orjson_codec import dumps_json
from app.shared.utils.http_helpers.request_logging import (
    RequestLogContext,
    request_log_metadata,
    should_skip_request_log,
)
from app.shared.utils.http_helpers.response_headers import (
    apply_response_headers,
    response_headers,
)
from app.shared.utils.http_helpers.trace_context import (
    resolve_endpoint_name,
    resolve_request_id,
    resolve_trace_context,
)


def install_request_logging_middleware(
    app: FastAPI,
    logger: logging.Logger,
) -> None:
    """Register JSON request logging middleware on the application.

    Args:
        app: FastAPI app to attach middleware to.
        logger: Logger used for request events.

    Returns:
        None.
    """

    @app.middleware("http")
    async def json_request_logging_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Log request success or failure as JSON.

        Args:
            request: See function signature.
            call_next: See function signature.

        Returns:
            Return value.
        """
        start = time.perf_counter()
        request_id = resolve_request_id(request)
        trace_id = resolve_trace_context(request)

        request.state.request_id = request_id
        request.state.trace_id = trace_id

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log_context = RequestLogContext(
                request_id=request_id,
                trace_id=trace_id,
                http_method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration_ms,
                func=resolve_endpoint_name(request),
            )
            log_context.log_exception(
                logger,
                message="request failed",
                event="request_failed",
            )
            return Response(
                content=dumps_json(
                    {"detail": "Internal Server Error", "request_id": request_id}
                ),
                status_code=500,
                media_type="application/json",
                headers=response_headers(request_id=request_id, trace_id=trace_id),
            )

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        level, event, message = request_log_metadata(response=response)
        log_context = RequestLogContext(
            request_id=request_id,
            trace_id=trace_id,
            http_method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            func=resolve_endpoint_name(request),
        )

        if not should_skip_request_log(
            path=request.url.path,
            status_code=response.status_code,
        ):
            log_context.log_outcome(
                logger,
                level=level,
                message=message,
                event=event,
            )

        apply_response_headers(
            response=response,
            request_id=request_id,
            trace_id=trace_id,
        )
        return response
