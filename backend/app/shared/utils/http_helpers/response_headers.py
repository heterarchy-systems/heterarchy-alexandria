"""HTTP response and header construction helpers."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi.responses import Response


def response_headers(request_id: str, trace_id: str) -> dict[str, str]:
    """Build response headers for request and trace identifiers.

    Args:
        request_id: See function signature.
        trace_id: See function signature.

    Returns:
        Return value.
    """
    headers = {"x-request-id": request_id}
    headers["x-trace-id"] = trace_id
    return headers


def json_response(
    payload: bytes | str,
    status_code: int,
    headers: Mapping[str, str] | None = None,
) -> Response:
    """Wrap serialized JSON bytes into an application/json Response.

    Args:
        payload: See function signature.
        status_code: See function signature.
        headers: Optional response headers for a protocol boundary.

    Returns:
        Return value.
    """
    response = Response(
        content=payload,
        status_code=status_code,
        media_type="application/json",
        headers=headers,
    )
    return response
