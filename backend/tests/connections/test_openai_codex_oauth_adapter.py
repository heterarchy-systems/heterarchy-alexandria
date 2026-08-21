"""Behavior tests for the OPENAI_CODEX OAuth HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

import anyio
import httpx
import pytest
from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import (
    OAuthPollStatus,
    ProviderType,
)
from app.connections.infrastructure.librarians.oauth import openai_codex_oauth_adapter
from app.connections.infrastructure.librarians.oauth.openai_codex_oauth_adapter import (
    OpenAICodexOAuthClient,
)
from app.connections.infrastructure.librarians.oauth.openai_codex_oauth_contracts import (
    OpenAICodexOAuthSettings,
)
from app.shared.exceptions.connections_exceptions import (
    ConnectionsProviderUnsupportedError,
)
from app.shared.types.extra_types import JSONObject

PROVIDER_ID = "00000000-0000-4000-8000-000000000888"


@dataclass(frozen=True, slots=True)
class RecordedPost:
    """Recorded HTTP POST boundary call."""

    url: str
    data: dict[str, str] | None
    json: dict[str, str] | None


class RecordingAsyncClient:
    """Fake HTTP client returning configured provider responses."""

    requests: ClassVar[list[RecordedPost]] = []
    responses: ClassVar[list[httpx.Response]] = []

    def __init__(self, timeout: float) -> None:
        """Accept the same timeout argument as httpx.AsyncClient."""
        self.timeout = timeout

    async def __aenter__(self) -> RecordingAsyncClient:
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Exit async context manager."""
        return None

    async def post(
        self,
        url: str,
        *,
        data: dict[str, str] | None = None,
        json: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Record the POST request and return the next configured response."""
        del headers
        self.requests.append(RecordedPost(url=url, data=data, json=json))
        return self.responses.pop(0)


def _provider(config: JSONObject) -> LibrarianProvider:
    """Build an OPENAI_CODEX provider row for adapter tests."""
    timestamp = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    return LibrarianProvider(
        id=PROVIDER_ID,
        name="codex-oauth",
        provider_type=ProviderType.OPENAI_CODEX.value,
        auth_type="OAUTH",
        enabled=True,
        config=config,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _codex_oauth_settings() -> OpenAICodexOAuthSettings:
    """Build deterministic Codex OAuth settings for adapter tests."""
    return OpenAICodexOAuthSettings(
        issuer="https://auth.openai.com",
        client_id="app_EMoamEEZ73f0CkXaXp7hrann",
        device_expires_in_seconds=15 * 60,
        min_poll_interval_seconds=3,
    )


def _codex_oauth_client() -> OpenAICodexOAuthClient:
    """Build an adapter client without depending on process env."""
    return OpenAICodexOAuthClient(settings=_codex_oauth_settings())


def test_openai_codex_oauth_rejects_unapproved_endpoint_before_http() -> None:
    """OAuth adapter should reject SSRF-shaped endpoint config before network I/O."""

    async def scenario() -> None:
        client = _codex_oauth_client()
        unsafe_config: JSONObject = {
            "device_authorization_url": "http://127.0.0.1/device",
            "token_url": "https://auth.openai.com/oauth/token",
            "client_id": "codex-client",
        }
        with pytest.raises(ConnectionsProviderUnsupportedError) as exc_info:
            await client.start_device_authorization(_provider(unsafe_config))

        assert str(exc_info.value) == (
            "OAuth config device_authorization_url must use an approved HTTPS endpoint"
        )

    anyio.run(scenario)


def test_openai_codex_oauth_rejects_allowed_host_wrong_path_before_http() -> None:
    """OAuth adapter should reject allowed-host URLs outside Codex OAuth paths."""

    async def scenario() -> None:
        client = _codex_oauth_client()
        unsafe_config: JSONObject = {
            "device_authorization_url": "https://auth.openai.com/redirect",
            "token_url": "https://auth.openai.com/oauth/token",
            "client_id": "codex-client",
        }
        with pytest.raises(ConnectionsProviderUnsupportedError) as exc_info:
            await client.start_device_authorization(_provider(unsafe_config))

        assert str(exc_info.value) == (
            "OAuth config device_authorization_url path is not approved for OPENAI_CODEX"
        )

    anyio.run(scenario)


def test_openai_codex_oauth_rejects_unapproved_configured_issuer_before_http() -> None:
    """OAuth adapter should validate env-derived endpoints before network I/O."""

    async def scenario() -> None:
        unsafe_settings = OpenAICodexOAuthSettings(
            issuer="https://api.openai.com",
            client_id="codex-client",
            device_expires_in_seconds=15 * 60,
            min_poll_interval_seconds=3,
        )
        client = OpenAICodexOAuthClient(settings=unsafe_settings)

        with pytest.raises(ConnectionsProviderUnsupportedError) as exc_info:
            await client.start_device_authorization(_provider({}))

        assert str(exc_info.value) == (
            "OAuth config device_authorization_url host is not approved for OPENAI_CODEX"
        )

    anyio.run(scenario)


def test_openai_codex_oauth_uses_configured_hermes_codex_metadata_without_manual_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex OAuth should use configured Hermes-style endpoints and client id."""
    RecordingAsyncClient.requests = []
    RecordingAsyncClient.responses = [
        httpx.Response(
            200,
            json={
                "user_code": "ABCD-1234",
                "device_auth_id": "device-auth-123",
                "interval": 2,
            },
        ),
        httpx.Response(
            200,
            json={
                "authorization_code": "auth-code-123",
                "code_verifier": "verifier-123",
            },
        ),
        httpx.Response(
            200,
            json={
                "access_token": "access-token-secret",
                "refresh_token": "refresh-token-secret",
                "expires_in": 3600,
            },
        ),
    ]
    monkeypatch.setattr(
        openai_codex_oauth_adapter.httpx,
        "AsyncClient",
        RecordingAsyncClient,
    )

    async def scenario() -> None:
        client = _codex_oauth_client()
        provider = _provider({})
        authorization = await client.start_device_authorization(provider)
        result = await client.poll_device_token(provider, authorization.device_code)

        assert authorization.user_code == "ABCD-1234"
        assert authorization.verification_uri == "https://auth.openai.com/codex/device"
        assert authorization.verification_uri_complete is None
        assert authorization.interval_seconds == 3
        assert result.status is OAuthPollStatus.CONNECTED
        assert result.token_set is not None
        assert result.token_set.access_token == "access-token-secret"
        assert result.token_set.refresh_token == "refresh-token-secret"
        assert RecordingAsyncClient.requests == [
            RecordedPost(
                url=("https://auth.openai.com/api/accounts/deviceauth/usercode"),
                data=None,
                json={"client_id": "app_EMoamEEZ73f0CkXaXp7hrann"},
            ),
            RecordedPost(
                url="https://auth.openai.com/api/accounts/deviceauth/token",
                data=None,
                json={
                    "device_auth_id": "device-auth-123",
                    "user_code": "ABCD-1234",
                },
            ),
            RecordedPost(
                url="https://auth.openai.com/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": "auth-code-123",
                    "redirect_uri": "https://auth.openai.com/deviceauth/callback",
                    "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                    "code_verifier": "verifier-123",
                },
                json=None,
            ),
        ]

    anyio.run(scenario)


def test_openai_codex_oauth_poll_maps_pending_status_without_token_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pending Codex authorization should not attempt token exchange."""
    RecordingAsyncClient.requests = []
    RecordingAsyncClient.responses = [
        httpx.Response(
            200,
            json={
                "user_code": "ABCD-1234",
                "device_auth_id": "device-auth-123",
                "interval": 5,
            },
        ),
        httpx.Response(403, json={"error": "authorization_pending"}),
    ]
    monkeypatch.setattr(
        openai_codex_oauth_adapter.httpx,
        "AsyncClient",
        RecordingAsyncClient,
    )

    async def scenario() -> None:
        client = _codex_oauth_client()
        provider = _provider({})
        authorization = await client.start_device_authorization(provider)
        result = await client.poll_device_token(provider, authorization.device_code)

        assert result.status is OAuthPollStatus.PENDING
        assert result.token_set is None
        assert result.message == "OAuth authorization is pending"
        assert len(RecordingAsyncClient.requests) == 2

    anyio.run(scenario)
