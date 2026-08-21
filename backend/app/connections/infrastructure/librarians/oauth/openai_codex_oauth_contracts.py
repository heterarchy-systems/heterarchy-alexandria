"""Request, secret, endpoint, and runtime settings for Codex OAuth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.platform.config.app_config import AppConfig
from typing_extensions import TypedDict

_CODEX_DEVICE_AUTHORIZATION_PATH: Final[str] = "/api/accounts/deviceauth/usercode"
_CODEX_DEVICE_TOKEN_PATH: Final[str] = "/api/accounts/deviceauth/token"
_CODEX_TOKEN_PATH: Final[str] = "/oauth/token"
_CODEX_VERIFICATION_PATH: Final[str] = "/codex/device"
_CODEX_REDIRECT_PATH: Final[str] = "/deviceauth/callback"
_AUTHORIZATION_CODE_GRANT_TYPE = "authorization_code"
_REFRESH_TOKEN_GRANT_TYPE = "refresh_token"


class CodexDeviceAuthorizationRequest(TypedDict, closed=True):
    """Request body for the OpenAI Codex device authorization endpoint."""

    client_id: str


class CodexDevicePollRequest(TypedDict, closed=True):
    """Request body for polling OpenAI Codex device authorization."""

    device_auth_id: str
    user_code: str


class CodexDeviceSecretPayload(TypedDict, closed=True):
    """Secret payload persisted while a Codex device flow is pending."""

    device_auth_id: str
    user_code: str


@dataclass(frozen=True, slots=True)
class OpenAICodexOAuthConfig:
    """Endpoint and client metadata for the OpenAI Codex device flow."""

    device_authorization_url: str
    device_token_url: str
    token_url: str
    client_id: str
    verification_uri: str
    redirect_uri: str


@dataclass(frozen=True, slots=True)
class OpenAICodexOAuthSettings:
    """Runtime OpenAI Codex OAuth metadata loaded from service config."""

    issuer: str
    client_id: str
    device_expires_in_seconds: int
    min_poll_interval_seconds: int

    @classmethod
    def from_app_config(
        cls,
        config: AppConfig | None = None,
    ) -> OpenAICodexOAuthSettings:
        """Build OpenAI Codex OAuth settings from AppConfig.

        Args:
            config: Optional AppConfig supplied by tests or dependency injection.

        Returns:
            OpenAICodexOAuthSettings: Required Codex OAuth runtime metadata.
        """
        app_config = AppConfig() if config is None else config
        return cls(
            issuer=app_config.codex_oauth_issuer.strip().rstrip("/"),
            client_id=app_config.codex_oauth_client_id.strip(),
            device_expires_in_seconds=(
                app_config.codex_oauth_device_expires_in_seconds
            ),
            min_poll_interval_seconds=(
                app_config.codex_oauth_min_poll_interval_seconds
            ),
        )
