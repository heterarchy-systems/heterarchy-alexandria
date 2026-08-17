"""Async HTTP backend client for heterarchy-alexandria MCP tools."""

from __future__ import annotations

import httpx
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings

from app.shared.types.extra_types import JSONObject, JSONValue
from app.shared.utils.config import settings_model_config
from app.shared.utils.http_helpers.json_payloads import (
    decode_json_body,
    extract_json_error_message,
    json_body_bytes,
)

DEFAULT_ALEXANDRIA_API_URL = "http://localhost:8000"
DEFAULT_MCP_TIMEOUT_SECONDS = 30.0

HttpHeaders = dict[str, str]
type QueryParamValue = bool | float | int | str | None


class AlexandriaApiSettings(BaseSettings):
    """Environment-backed settings for the MCP HTTP client."""

    model_config = {
        **settings_model_config(env_prefix=""),
        "populate_by_name": True,
    }

    base_url: str = Field(
        default=DEFAULT_ALEXANDRIA_API_URL,
        validation_alias=AliasChoices("ALEXANDRIA_API_URL", "HERMES_API_URL"),
    )
    timeout: float = Field(
        default=DEFAULT_MCP_TIMEOUT_SECONDS,
        validation_alias="ALEXANDRIA_API_TIMEOUT_SECONDS",
    )

    @classmethod
    def from_env(cls) -> AlexandriaApiSettings:
        """Create settings through the typed MCP settings boundary.

        Args:
            None.

        Returns:
            Client settings for backend API calls.
        """
        settings = cls()
        return settings

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        """Normalize the configured backend URL.

        Args:
            value: Raw URL from environment or default.

        Returns:
            Normalized URL without a trailing slash.
        """
        stripped = value.strip()
        return (stripped or DEFAULT_ALEXANDRIA_API_URL).rstrip("/")

    @field_validator("timeout")
    @classmethod
    def normalize_timeout(cls, value: float) -> float:
        """Clamp configured timeout to at least one second.

        Args:
            value: Parsed timeout value.

        Returns:
            Bounded timeout value.
        """
        return max(1.0, float(value))


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
        settings: AlexandriaApiSettings,
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
        *,
        params: JSONObject,
    ) -> JSONValue:
        """Send a POST request whose bounded operation inputs are query parameters.

        Args:
            path: Value supplied to post_query.
            params: Value supplied to post_query.

        Returns:
            Result produced by post_query.
        """
        return await self._request("POST", path, None, params)

    async def delete(self, path: str) -> JSONValue:
        """Send a DELETE request to the backend.

        Args:
            path: Backend path beginning with slash.

        Returns:
            Decoded JSON response, or None for empty 204 responses.
        """
        response = await self._request("DELETE", path, None, None)
        return response

    async def _request(
        self,
        method: str,
        path: str,
        payload: JSONValue | None,
        params: JSONObject | None,
    ) -> JSONValue:
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
