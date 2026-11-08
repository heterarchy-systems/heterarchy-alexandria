"""Async HTTP backend client for heterarchy-alexandria MCP tools."""

from __future__ import annotations

import httpx

from app.mcp_server.type_validate.oauth.config_contracts import McpApiConfig
from app.shared.types.extra_types import JSONObject, JSONValue
from app.shared.utils.http_helpers.json_payloads import (
    decode_json_body,
    extract_json_error_message,
    json_body_bytes,
)

HttpHeaders = dict[str, str]
type QueryParamValue = bool | float | int | str | None


class AlexandriaApiConfigurationError(Exception):
    """Invalid MCP backend API configuration."""


class AlexandriaApiError(Exception):
    """Backend HTTP error surfaced to MCP tools."""

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize an API error.

        Args:
            status_code: HTTP status code or zero for transport failures.
            message: Stable error message.

        Returns:
            None.
        """
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class AlexandriaApiClient:
    """Native async HTTP client for backend API calls from MCP tools."""

    def __init__(
        self,
        settings: McpApiConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialize the API client.

        Args:
            settings: Backend API settings.
            transport: Optional async HTTP transport for tests.

        Returns:
            None.
        """
        self._settings = settings
        self._transport = transport

    async def get(self, path: str, params: JSONObject | None = None) -> JSONValue:
        """Send a GET request to the backend.

        Args:
            path: Backend path beginning with slash.
            params: Optional query parameters.

        Returns:
            Decoded JSON response.
        """
        payload = await self._request("GET", path, None, params)
        return payload

    async def post(self, path: str, payload: JSONObject) -> JSONValue:
        """Send a POST request to the backend.

        Args:
            path: Backend path beginning with slash.
            payload: JSON request body.

        Returns:
            Decoded JSON response.
        """
        response = await self._request("POST", path, payload, None)
        return response

    async def post_query(
        self,
        path: str,
        params: JSONObject,
    ) -> JSONValue:
        """Send a POST request whose bounded operation inputs are query parameters.

        Args:
            path: Backend path beginning with slash.
            params: Query parameters encoding the bounded operation inputs.

        Returns:
            Decoded JSON response.
        """
        return await self._request("POST", path, None, params)

    async def delete(self, path: str, params: JSONObject | None = None) -> JSONValue:
        """Send a DELETE request to the backend.

        Args:
            path: Backend path beginning with slash.
            params: Optional query parameters.

        Returns:
            Decoded JSON response, or None for empty 204 responses.
        """
        response = await self._request("DELETE", path, None, params)
        return response

    async def _request(
        self,
        method: str,
        path: str,
        payload: JSONValue | None,
        params: JSONObject | None,
    ) -> JSONValue:
        """Send an HTTP request and decode its JSON response.

        Args:
            method: HTTP method verb.
            path: Backend path beginning with slash.
            payload: Optional JSON request body.
            params: Optional query parameters.

        Returns:
            Decoded JSON response value.
        """
        request_body = None if payload is None else json_body_bytes(payload)
        headers: HttpHeaders = {"Accept": "application/json"}
        if request_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.base_url,
                timeout=httpx.Timeout(self._settings.timeout),
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    params=_query_params(params),
                    content=request_body,
                    headers=headers,
                )
        except httpx.RequestError as exc:
            message = str(exc)
            raise AlexandriaApiError(0, message) from exc
        if response.status_code < 200 or response.status_code >= 300:
            message = extract_json_error_message(response.content)
            raise AlexandriaApiError(response.status_code, message)
        decoded = decode_json_body(response.content)
        return decoded


def _query_params(params: JSONObject | None) -> list[tuple[str, QueryParamValue]]:
    """Flatten a JSON parameter mapping into httpx query-parameter tuples.

    Args:
        params: Optional query parameter mapping.

    Returns:
        Flattened list of key/string-value query parameter pairs.
    """
    if params is None:
        return []
    compact: list[tuple[str, QueryParamValue]] = []
    for key, value in params.items():
        if value is None or isinstance(value, dict):
            continue
        if isinstance(value, list):
            compact.extend((key, str(item)) for item in value)
            continue
        compact.append((key, str(value)))
    return compact
