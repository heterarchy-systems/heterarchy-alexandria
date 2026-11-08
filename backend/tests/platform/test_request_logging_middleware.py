"""Request logging middleware response header regressions."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from app.platform.middleware.request_logging import install_request_logging_middleware


def test_normal_response_preserves_body_and_receives_request_headers() -> None:
    """The middleware keeps endpoint output and adds request/trace identifiers."""
    app = FastAPI()

    @app.get("/normal")
    async def normal_response() -> Response:
        return Response(
            content=b"normal response",
            status_code=202,
            headers={"x-endpoint-header": "preserved"},
        )

    install_request_logging_middleware(app, logger=logging.getLogger(__name__))

    response = TestClient(app).get(
        "/normal",
        headers={
            "x-request-id": "request-123",
            "x-correlation-id": "correlation-ignored",
            "x-trace-id": "trace-456",
        },
    )

    assert response.status_code == 202
    assert response.content == b"normal response"
    assert response.headers["x-endpoint-header"] == "preserved"
    assert response.headers["x-request-id"] == "request-123"
    assert response.headers["x-trace-id"] == "trace-456"


def test_exception_response_uses_correlation_and_trace_headers() -> None:
    """The middleware preserves correlation fallback on its JSON error response."""
    app = FastAPI()

    @app.get("/failure")
    async def failing_response() -> None:
        raise RuntimeError("endpoint failure")

    install_request_logging_middleware(app, logger=logging.getLogger(__name__))

    response = TestClient(app).get(
        "/failure",
        headers={
            "x-correlation-id": "correlation-789",
            "x-trace-id": "trace-987",
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal Server Error",
        "request_id": "correlation-789",
    }
    assert response.headers["x-request-id"] == "correlation-789"
    assert response.headers["x-trace-id"] == "trace-987"
