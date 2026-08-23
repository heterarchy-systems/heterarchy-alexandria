"""HTTP OAuth device-flow client for OPENAI_CODEX librarian providers."""

from __future__ import annotations

import httpx

from app.connections.application.librarians.oauth_client import OAuthProviderClient
from app.connections.domain.contracts.librarian_oauth_contracts import (
    OAuthDeviceAuthorization,
    OAuthPollResult,
    OAuthTokenSet,
)
from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import OAuthPollStatus
from app.connections.infrastructure.librarians.oauth.openai_codex_oauth_contracts import (
    CodexDeviceAuthorizationRequest,
    CodexDevicePollRequest,
    CodexDeviceSecretPayload,
    OpenAICodexOAuthConfig,
    OpenAICodexOAuthSettings,
)
from app.connections.infrastructure.librarians.oauth.openai_codex_oauth_payloads import (
    _device_expires_at_from_payload,
    _device_secret_payload,
    _device_secret_value,
    _error_response_payload,
    _oauth_config,
    _oauth_error_poll_result,
    _pending_poll_result,
    _poll_interval_from_payload,
    _required_string,
    _response_payload,
    _slow_down_poll_result,
    _token_set_from_payload,
)
from app.shared.exceptions.connections_exceptions import (
    ConnectionsProviderUnsupportedError,
)

_AUTHORIZATION_CODE_GRANT_TYPE = "authorization_code"
_REFRESH_TOKEN_GRANT_TYPE = "refresh_token"

__all__ = (
    "CodexDeviceAuthorizationRequest",
    "CodexDevicePollRequest",
    "CodexDeviceSecretPayload",
    "OpenAICodexOAuthClient",
    "OpenAICodexOAuthConfig",
    "OpenAICodexOAuthSettings",
)


class OpenAICodexOAuthClient(OAuthProviderClient):
    """OAuth client that follows the Hermes OpenAI Codex device flow."""

    def __init__(self, settings: OpenAICodexOAuthSettings | None = None) -> None:
        """Initialize the client with service-loaded OAuth settings.

        Args:
            settings: Optional OpenAI Codex OAuth settings override.
        """
        self._settings = (
            OpenAICodexOAuthSettings.from_app_config() if settings is None else settings
        )

    async def start_device_authorization(
        self,
        provider: LibrarianProvider,
    ) -> OAuthDeviceAuthorization:
        """Start device authorization at the OpenAI Codex endpoint.

        Args:
            provider: OPENAI_CODEX provider read model.

        Returns:
            OAuthDeviceAuthorization: Device-flow values.
        """
        config = _oauth_config(provider.config, self._settings)
        request_payload = CodexDeviceAuthorizationRequest(client_id=config.client_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                config.device_authorization_url,
                json=request_payload,
                headers={"Content-Type": "application/json"},
            )
        if response.status_code >= 400:
            raise ConnectionsProviderUnsupportedError(
                "OAuth device authorization failed"
            )
        payload = _response_payload(response)

        device_auth_id = _required_string(payload, "device_auth_id")
        user_code = _required_string(payload, "user_code")
        authorization = OAuthDeviceAuthorization(
            device_code=_device_secret_value(
                device_auth_id=device_auth_id,
                user_code=user_code,
            ),
            user_code=user_code,
            verification_uri=config.verification_uri,
            verification_uri_complete=None,
            expires_at=_device_expires_at_from_payload(payload, self._settings),
            interval_seconds=_poll_interval_from_payload(payload, self._settings),
        )
        return authorization

    async def poll_device_token(
        self,
        provider: LibrarianProvider,
        device_code: str,
    ) -> OAuthPollResult:
        """Poll Codex device authorization and exchange code for tokens.

        Args:
            provider: OPENAI_CODEX provider read model.
            device_code: Secret device authorization context.

        Returns:
            OAuthPollResult: Poll status and optional token set.
        """
        config = _oauth_config(provider.config, self._settings)
        device_context = _device_secret_payload(device_code)
        poll_payload = CodexDevicePollRequest(
            device_auth_id=device_context["device_auth_id"],
            user_code=device_context["user_code"],
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            device_response = await client.post(
                config.device_token_url,
                json=poll_payload,
                headers={"Content-Type": "application/json"},
            )
            if device_response.status_code in {403, 404}:
                return _pending_poll_result()
            if device_response.status_code == 429:
                return _slow_down_poll_result()
            if device_response.status_code >= 400:
                payload = _error_response_payload(device_response)
                return _oauth_error_poll_result(payload)

            code_payload = _response_payload(device_response)
            token_response = await client.post(
                config.token_url,
                data={
                    "grant_type": _AUTHORIZATION_CODE_GRANT_TYPE,
                    "code": _required_string(code_payload, "authorization_code"),
                    "redirect_uri": config.redirect_uri,
                    "client_id": config.client_id,
                    "code_verifier": _required_string(
                        code_payload,
                        "code_verifier",
                    ),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if token_response.status_code >= 400:
            payload = _error_response_payload(token_response)
            return _oauth_error_poll_result(payload)

        payload = _response_payload(token_response)
        token_set = _token_set_from_payload(payload)
        result = OAuthPollResult(
            status=OAuthPollStatus.CONNECTED,
            token_set=token_set,
            interval_seconds=None,
            message=None,
        )
        return result

    async def refresh_token(
        self,
        provider: LibrarianProvider,
        refresh_token: str,
    ) -> OAuthTokenSet:
        """Refresh an OAuth token through the OpenAI token endpoint.

        Args:
            provider: OPENAI_CODEX provider read model.
            refresh_token: Secret refresh token from encrypted storage.

        Returns:
            OAuthTokenSet: Rotated token values.
        """
        config = _oauth_config(provider.config, self._settings)
        form = {
            "grant_type": _REFRESH_TOKEN_GRANT_TYPE,
            "refresh_token": refresh_token,
            "client_id": config.client_id,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                config.token_url,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if response.status_code >= 400:
            raise ConnectionsProviderUnsupportedError("OAuth token refresh failed")
        payload = _response_payload(response)
        token_set = _token_set_from_payload(payload)
        return token_set
