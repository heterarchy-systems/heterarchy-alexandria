"""Endpoint resolution and response parsing for the Codex OAuth device flow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import httpx

from app.connections.application.librarians.credential_policy import (
    ensure_openai_codex_oauth_config_is_safe,
)
from app.connections.domain.contracts.librarian_oauth_contracts import (
    OAuthPollResult,
    OAuthTokenSet,
)
from app.connections.domain.event_enum.provider_enums import (
    AuthType,
    OAuthPollStatus,
    ProviderType,
)
from app.connections.infrastructure.librarians.oauth.openai_codex_oauth_contracts import (
    CodexDeviceSecretPayload,
    OpenAICodexOAuthConfig,
    OpenAICodexOAuthSettings,
)
from app.shared.exceptions.connections_exceptions import (
    ConnectionsProviderUnsupportedError,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_CODEX_DEVICE_AUTHORIZATION_PATH: Final[str] = "/api/accounts/deviceauth/usercode"
_CODEX_DEVICE_TOKEN_PATH: Final[str] = "/api/accounts/deviceauth/token"
_CODEX_TOKEN_PATH: Final[str] = "/oauth/token"
_CODEX_VERIFICATION_PATH: Final[str] = "/codex/device"
_CODEX_REDIRECT_PATH: Final[str] = "/deviceauth/callback"


def _oauth_config(
    config: JSONObject,
    settings: OpenAICodexOAuthSettings,
) -> OpenAICodexOAuthConfig:
    """Execute oauth config.

    Args:
        config: Typed configuration used by this operation.
        settings: Settings used by this operation.

    Returns:
        OpenAICodexOAuthConfig result produced by oauth config.
    """
    issuer = _config_string(config, "issuer", default=settings.issuer).rstrip("/")
    oauth_config = OpenAICodexOAuthConfig(
        device_authorization_url=_config_string(
            config,
            "device_authorization_url",
            default=f"{issuer}{_CODEX_DEVICE_AUTHORIZATION_PATH}",
        ),
        device_token_url=_config_string(
            config,
            "device_token_url",
            default=f"{issuer}{_CODEX_DEVICE_TOKEN_PATH}",
        ),
        token_url=_config_string(
            config,
            "token_url",
            default=f"{issuer}{_CODEX_TOKEN_PATH}",
        ),
        client_id=_config_string(
            config,
            "client_id",
            default=settings.client_id,
        ),
        verification_uri=_config_string(
            config,
            "verification_uri",
            default=f"{issuer}{_CODEX_VERIFICATION_PATH}",
        ),
        redirect_uri=_config_string(
            config,
            "redirect_uri",
            default=f"{issuer}{_CODEX_REDIRECT_PATH}",
        ),
    )
    ensure_openai_codex_oauth_config_is_safe(
        provider_type=ProviderType.OPENAI_CODEX,
        auth_type=AuthType.OAUTH,
        config={
            "device_authorization_url": oauth_config.device_authorization_url,
            "device_token_url": oauth_config.device_token_url,
            "issuer": issuer,
            "redirect_uri": oauth_config.redirect_uri,
            "token_url": oauth_config.token_url,
            "verification_uri": oauth_config.verification_uri,
        },
    )
    return oauth_config


def _config_string(config: JSONObject, key: str, default: str) -> str:
    """Execute config string.

    Args:
        config: Typed configuration used by this operation.
        key: Key used by this operation.
        default: Default used by this operation.

    Returns:
        str result produced by config string.
    """
    value = config.get(key)
    if value is None:
        return default
    if isinstance(value, str) and value:
        return value
    raise ConnectionsProviderUnsupportedError(
        f"OAuth config {key} must be a non-empty string"
    )


def _response_payload(response: httpx.Response) -> JSONObject:
    """Execute response payload.

    Args:
        response: Response value being processed.

    Returns:
        JSONObject result produced by response payload.
    """
    try:
        decoded = loads_json(response.text)
    except ValueError as exc:
        raise ConnectionsProviderUnsupportedError(
            "OAuth provider returned invalid JSON"
        ) from exc
    if isinstance(decoded, dict):
        return decoded
    raise ConnectionsProviderUnsupportedError("OAuth provider returned invalid JSON")


def _error_response_payload(response: httpx.Response) -> JSONObject:
    """Execute error response payload.

    Args:
        response: Response value being processed.

    Returns:
        JSONObject result produced by error response payload.
    """
    try:
        return _response_payload(response)
    except ConnectionsProviderUnsupportedError:
        return {}


def _pending_poll_result() -> OAuthPollResult:
    """Execute pending poll result.

    Returns:
        OAuthPollResult result produced by pending poll result.
    """
    return OAuthPollResult(
        status=OAuthPollStatus.PENDING,
        token_set=None,
        interval_seconds=None,
        message="OAuth authorization is pending",
    )


def _slow_down_poll_result() -> OAuthPollResult:
    """Execute slow down poll result.

    Returns:
        OAuthPollResult result produced by slow down poll result.
    """
    return OAuthPollResult(
        status=OAuthPollStatus.SLOW_DOWN,
        token_set=None,
        interval_seconds=None,
        message="OAuth polling should slow down",
    )


def _oauth_error_poll_result(payload: JSONObject) -> OAuthPollResult:
    """Execute oauth error poll result.

    Args:
        payload: Validated payload for this operation.

    Returns:
        OAuthPollResult result produced by oauth error poll result.
    """
    error = _optional_string(payload, "error")
    if error in {"authorization_pending", "pending"}:
        return _pending_poll_result()
    if error == "slow_down":
        return _slow_down_poll_result()
    if error in {"expired_token", "expired"}:
        return OAuthPollResult(
            status=OAuthPollStatus.EXPIRED,
            token_set=None,
            interval_seconds=None,
            message="OAuth device flow expired",
        )
    return OAuthPollResult(
        status=OAuthPollStatus.FAILED,
        token_set=None,
        interval_seconds=None,
        message="OAuth provider rejected the device flow",
    )


def _device_secret_value(device_auth_id: str, user_code: str) -> str:
    """Execute device secret value.

    Args:
        device_auth_id: Identifier for device auth.
        user_code: User code used by this operation.

    Returns:
        str result produced by device secret value.
    """
    secret_payload = CodexDeviceSecretPayload(
        device_auth_id=device_auth_id,
        user_code=user_code,
    )
    json_payload: JSONObject = {
        "device_auth_id": secret_payload["device_auth_id"],
        "user_code": secret_payload["user_code"],
    }
    return dumps_json(json_payload).decode("utf-8")


def _device_secret_payload(device_code: str) -> CodexDeviceSecretPayload:
    """Execute device secret payload.

    Args:
        device_code: Device code used by this operation.

    Returns:
        CodexDeviceSecretPayload result produced by device secret payload.
    """
    try:
        decoded = loads_json(device_code)
    except ValueError as exc:
        raise ConnectionsProviderUnsupportedError(
            "OAuth device authorization context is invalid"
        ) from exc
    if not isinstance(decoded, dict):
        raise ConnectionsProviderUnsupportedError(
            "OAuth device authorization context is invalid"
        )
    return CodexDeviceSecretPayload(
        device_auth_id=_required_string(decoded, "device_auth_id"),
        user_code=_required_string(decoded, "user_code"),
    )


def _token_set_from_payload(payload: JSONObject) -> OAuthTokenSet:
    """Execute token set from payload.

    Args:
        payload: Validated payload for this operation.

    Returns:
        OAuthTokenSet result produced by token set from payload.
    """
    return OAuthTokenSet(
        access_token=_required_string(payload, "access_token"),
        refresh_token=_optional_string(payload, "refresh_token"),
        expires_at=_expires_at_from_payload(payload),
        token_type=_optional_string(payload, "token_type") or "Bearer",
        scope=_optional_string(payload, "scope"),
    )


def _expires_at_from_payload(payload: JSONObject) -> datetime:
    """Execute expires at from payload.

    Args:
        payload: Validated payload for this operation.

    Returns:
        datetime result produced by expires at from payload.
    """
    expires_at_value = _optional_string(payload, "expires_at")
    if expires_at_value is not None:
        try:
            parsed = datetime.fromisoformat(expires_at_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ConnectionsProviderUnsupportedError(
                "OAuth expires_at is invalid"
            ) from exc
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    expires_in = _optional_int(payload, "expires_in", default=3600)
    return datetime.now(UTC) + timedelta(seconds=expires_in)


def _device_expires_at_from_payload(
    payload: JSONObject,
    settings: OpenAICodexOAuthSettings,
) -> datetime:
    """Execute device expires at from payload.

    Args:
        payload: Validated payload for this operation.
        settings: Settings used by this operation.

    Returns:
        datetime result produced by device expires at from payload.
    """
    expires_in = _optional_int(
        payload,
        "expires_in",
        default=settings.device_expires_in_seconds,
    )
    return datetime.now(UTC) + timedelta(seconds=expires_in)


def _poll_interval_from_payload(
    payload: JSONObject,
    settings: OpenAICodexOAuthSettings,
) -> int:
    """Execute poll interval from payload.

    Args:
        payload: Validated payload for this operation.
        settings: Settings used by this operation.

    Returns:
        int result produced by poll interval from payload.
    """
    interval = _optional_int(payload, "interval", default=5)
    return max(settings.min_poll_interval_seconds, interval)


def _required_string(payload: JSONObject, key: str) -> str:
    """Execute required string.

    Args:
        payload: Validated payload for this operation.
        key: Key used by this operation.

    Returns:
        str result produced by required string.
    """
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    raise ConnectionsProviderUnsupportedError(
        f"OAuth response missing required field: {key}"
    )


def _optional_string(payload: JSONObject, key: str) -> str | None:
    """Execute optional string.

    Args:
        payload: Validated payload for this operation.
        key: Key used by this operation.

    Returns:
        str | None result produced by optional string.
    """
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(payload: JSONObject, key: str, default: int) -> int:
    """Execute optional int.

    Args:
        payload: Validated payload for this operation.
        key: Key used by this operation.
        default: Default used by this operation.

    Returns:
        int result produced by optional int.
    """
    value: JSONValue | None = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default
