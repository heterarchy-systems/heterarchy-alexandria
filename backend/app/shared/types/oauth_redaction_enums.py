"""Feature-owned oauth redaction enums."""

from __future__ import annotations

from enum import StrEnum


class OAuthSensitiveResponseKey(StrEnum):
    """OAuth response fields that must not be exposed to agents."""

    ACCESS_TOKEN = "access_token"
    API_KEY = "api_key"
    CLIENT_SECRET = "client_secret"
    DEVICE_CODE = "device_code"
    ID_TOKEN = "id_token"
    OAUTH_ACCESS_TOKEN = "oauth_access_token"
    OAUTH_DEVICE_CODE = "oauth_device_code"
    OAUTH_REFRESH_TOKEN = "oauth_refresh_token"
    REFRESH_TOKEN = "refresh_token"
    SECRET = "secret"
    SECRETS = "secrets"
    TOKEN = "token"
    TOKENS = "tokens"


class OAuthDeviceUserInstructionKey(StrEnum):
    """Device-flow instruction fields hidden except for local operator UX."""

    USER_CODE = "user_code"
    VERIFICATION_URI_COMPLETE = "verification_uri_complete"
