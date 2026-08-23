"""Pure credential policy checks for librarian providers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final
from urllib.parse import urlparse

from app.connections.domain.event_enum.credential_policy_enums import (
    OpenAICodexOAuthAllowedHost,
    OpenAICodexOAuthAllowedPath,
    OpenAICodexOAuthConfigKey,
)
from app.connections.domain.event_enum.provider_enums import (
    AuthType,
    ConfigCredentialKey,
    ProviderType,
)
from app.shared.exceptions.connections_exceptions import (
    ConnectionsProviderUnsupportedError,
)
from app.shared.types.extra_types import JSONObject, JSONValue

SUPPORTED_PROVIDER_AUTH_TYPES: Final[Mapping[ProviderType, frozenset[AuthType]]] = {
    ProviderType.OPENAI: frozenset({AuthType.API_KEY}),
    ProviderType.OPENAI_CODEX: frozenset({AuthType.OAUTH}),
}
OPENAI_CODEX_OAUTH_URL_KEYS: Final[tuple[OpenAICodexOAuthConfigKey, ...]] = (
    OpenAICodexOAuthConfigKey.DEVICE_AUTHORIZATION_URL,
    OpenAICodexOAuthConfigKey.DEVICE_TOKEN_URL,
    OpenAICodexOAuthConfigKey.ISSUER,
    OpenAICodexOAuthConfigKey.REDIRECT_URI,
    OpenAICodexOAuthConfigKey.TOKEN_URL,
    OpenAICodexOAuthConfigKey.VERIFICATION_URI,
)
OPENAI_CODEX_OAUTH_PROTECTED_CONFIG_KEYS: Final[
    tuple[OpenAICodexOAuthConfigKey, ...]
] = (
    OpenAICodexOAuthConfigKey.DEVICE_AUTHORIZATION_URL,
    OpenAICodexOAuthConfigKey.DEVICE_TOKEN_URL,
    OpenAICodexOAuthConfigKey.CLIENT_ID,
    OpenAICodexOAuthConfigKey.ISSUER,
    OpenAICodexOAuthConfigKey.REDIRECT_URI,
    OpenAICodexOAuthConfigKey.SCOPE,
    OpenAICodexOAuthConfigKey.TOKEN_URL,
    OpenAICodexOAuthConfigKey.VERIFICATION_URI,
)
OPENAI_CODEX_OAUTH_ALLOWED_HOSTS: Final[frozenset[OpenAICodexOAuthAllowedHost]] = (
    frozenset({OpenAICodexOAuthAllowedHost.AUTH_OPENAI})
)
OPENAI_CODEX_OAUTH_ALLOWED_PATHS: Final[
    Mapping[OpenAICodexOAuthConfigKey, frozenset[OpenAICodexOAuthAllowedPath]]
] = {
    OpenAICodexOAuthConfigKey.DEVICE_AUTHORIZATION_URL: frozenset(
        {OpenAICodexOAuthAllowedPath.DEVICE_AUTHORIZATION}
    ),
    OpenAICodexOAuthConfigKey.DEVICE_TOKEN_URL: frozenset(
        {OpenAICodexOAuthAllowedPath.DEVICE_TOKEN}
    ),
    OpenAICodexOAuthConfigKey.ISSUER: frozenset(
        {OpenAICodexOAuthAllowedPath.EMPTY, OpenAICodexOAuthAllowedPath.ROOT}
    ),
    OpenAICodexOAuthConfigKey.REDIRECT_URI: frozenset(
        {OpenAICodexOAuthAllowedPath.DEVICE_CALLBACK}
    ),
    OpenAICodexOAuthConfigKey.TOKEN_URL: frozenset(
        {OpenAICodexOAuthAllowedPath.OAUTH_TOKEN}
    ),
    OpenAICodexOAuthConfigKey.VERIFICATION_URI: frozenset(
        {OpenAICodexOAuthAllowedPath.CODEX_DEVICE}
    ),
}


def supported_provider_auth_types(provider_type: ProviderType) -> frozenset[AuthType]:
    """Return auth modes supported by a provider type.

    Args:
        provider_type: Provider implementation family.

    Returns:
        Supported auth modes for the provider type.
    """
    supported_auth_types = SUPPORTED_PROVIDER_AUTH_TYPES[provider_type]
    return supported_auth_types


def openai_codex_oauth_allowed_paths_for(
    key: OpenAICodexOAuthConfigKey,
) -> frozenset[OpenAICodexOAuthAllowedPath]:
    """Return approved OpenAI Codex OAuth URL paths for one config key.

    Args:
        key: OAuth config key.

    Returns:
        Approved paths for the key.
    """
    allowed_paths = OPENAI_CODEX_OAUTH_ALLOWED_PATHS[key]
    return allowed_paths


def ensure_provider_config_has_no_credentials(config: JSONObject) -> None:
    """Reject credentials embedded in provider config payloads.

    Args:
        config: Public provider configuration payload.

    Returns:
        None.

    Raises:
        ConnectionsProviderUnsupportedError: When config includes credential-shaped keys.
    """
    if _config_contains_credential_key(config):
        raise ConnectionsProviderUnsupportedError(
            "Provider config must not include credential fields"
        )


def ensure_provider_auth_type_is_supported(
    provider_type: ProviderType,
    auth_type: AuthType,
) -> None:
    """Validate provider/auth compatibility before checking credential material.

    Args:
        provider_type: Provider implementation family.
        auth_type: Requested authentication mode.

    Returns:
        None.

    Raises:
        ConnectionsProviderUnsupportedError: When the provider/auth combination is invalid.
    """
    if auth_type not in supported_provider_auth_types(provider_type):
        raise ConnectionsProviderUnsupportedError(
            f"Provider type {provider_type.value} does not support {auth_type.value} auth"
        )


def ensure_create_credentials_are_present(
    provider_type: ProviderType,
    auth_type: AuthType,
    api_key: str | None,
    oauth_access_token: str | None,
) -> None:
    """Validate credentials required for provider creation.

    Args:
        provider_type: Provider implementation family.
        auth_type: Requested authentication mode.
        api_key: Optional API key credential.
        oauth_access_token: Optional OAuth access token.

    Returns:
        None.

    Raises:
        ConnectionsProviderUnsupportedError: When required credentials are absent.
    """
    ensure_provider_auth_type_is_supported(
        provider_type=provider_type,
        auth_type=auth_type,
    )
    if auth_type is AuthType.API_KEY and not api_key:
        raise ConnectionsProviderUnsupportedError("API_KEY auth requires api_key")


def ensure_openai_codex_oauth_config_is_safe(
    provider_type: ProviderType,
    auth_type: AuthType,
    config: JSONObject,
) -> None:
    """Validate mutable OAuth endpoint config cannot become an SSRF sink.

    Args:
        provider_type: Provider implementation family.
        auth_type: Requested authentication mode.
        config: Public provider config payload.

    Returns:
        None.

    Raises:
        ConnectionsProviderUnsupportedError: When OAuth endpoints are unsafe.
    """
    if (
        provider_type is not ProviderType.OPENAI_CODEX
        or auth_type is not AuthType.OAUTH
    ):
        return

    _ensure_openai_codex_oauth_config_payload_is_safe(config)


def openai_codex_oauth_config_has_protected_change(
    previous_config: JSONObject,
    next_config: JSONObject,
) -> bool:
    """Return whether token-routing OAuth config changed.

    Args:
        previous_config: Current persisted public provider config.
        next_config: Requested replacement public provider config.

    Returns:
        bool: True when protected OAuth routing fields changed.
    """
    for key in OPENAI_CODEX_OAUTH_PROTECTED_CONFIG_KEYS:
        if _config_text_value(previous_config, key.value) != _config_text_value(
            next_config,
            key.value,
        ):
            return True
    return False


def _ensure_openai_codex_oauth_config_payload_is_safe(config: JSONObject) -> None:
    """Ensure openai codex oauth config payload is safe.

    Args:
        config: Typed configuration used by this operation.
    """
    for key in OPENAI_CODEX_OAUTH_URL_KEYS:
        value = config.get(key.value)
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            raise ConnectionsProviderUnsupportedError(
                f"OAuth config {key.value} must be a URL string"
            )
        _ensure_openai_codex_oauth_https_allowed_host(key, value)


def _ensure_openai_codex_oauth_https_allowed_host(
    key: OpenAICodexOAuthConfigKey,
    url: str,
) -> None:
    """Ensure openai codex oauth https allowed host.

    Args:
        key: Key used by this operation.
        url: Url used by this operation.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if parsed.scheme != "https" or hostname is None:
        raise ConnectionsProviderUnsupportedError(
            f"OAuth config {key.value} must use an approved HTTPS endpoint"
        )
    if parsed.username is not None or parsed.password is not None:
        raise ConnectionsProviderUnsupportedError(
            f"OAuth config {key.value} must not include userinfo"
        )
    if parsed.port is not None and parsed.port != 443:
        raise ConnectionsProviderUnsupportedError(
            f"OAuth config {key.value} must not include a custom port"
        )
    if hostname.lower() not in _openai_codex_oauth_allowed_host_values():
        raise ConnectionsProviderUnsupportedError(
            f"OAuth config {key.value} host is not approved for OPENAI_CODEX"
        )
    if (
        parsed.path not in _openai_codex_oauth_allowed_path_values_for(key)
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ConnectionsProviderUnsupportedError(
            f"OAuth config {key.value} path is not approved for OPENAI_CODEX"
        )


def _openai_codex_oauth_allowed_host_values() -> frozenset[str]:
    """Execute openai codex oauth allowed host values.

    Returns:
        frozenset[str] result produced by openai codex oauth allowed host values.
    """
    allowed_host_values = frozenset(
        host.value for host in OPENAI_CODEX_OAUTH_ALLOWED_HOSTS
    )
    return allowed_host_values


def _openai_codex_oauth_allowed_path_values_for(
    key: OpenAICodexOAuthConfigKey,
) -> frozenset[str]:
    """Execute openai codex oauth allowed path values for.

    Args:
        key: Key used by this operation.

    Returns:
        frozenset[str] result produced by openai codex oauth allowed path values for.
    """
    allowed_path_values = frozenset(
        path.value for path in openai_codex_oauth_allowed_paths_for(key)
    )
    return allowed_path_values


def _config_contains_credential_key(value: JSONValue) -> bool:
    """Execute config contains credential key.

    Args:
        value: Value being processed.

    Returns:
        Whether config contains credential key.
    """
    if isinstance(value, dict):
        for key, nested in value.items():
            if _is_config_credential_key(_normalized_config_key(key)):
                return True
            if _config_contains_credential_key(nested):
                return True
        return False
    if isinstance(value, list):
        contains_credential = any(
            _config_contains_credential_key(item) for item in value
        )
        return contains_credential
    return False


def _is_config_credential_key(key: str) -> bool:
    """Return whether config credential key.

    Args:
        key: Key used by this operation.

    Returns:
        Whether config credential key.
    """
    try:
        ConfigCredentialKey(key)
    except ValueError:
        return False
    return True


def _normalized_config_key(key: str) -> str:
    """Execute normalized config key.

    Args:
        key: Key used by this operation.

    Returns:
        str result produced by normalized config key.
    """
    normalized_key = key.strip().lower().replace("-", "_")
    return normalized_key


def _config_text_value(config: JSONObject, key: str) -> str | None:
    """Execute config text value.

    Args:
        config: Typed configuration used by this operation.
        key: Key used by this operation.

    Returns:
        str | None result produced by config text value.
    """
    value = config.get(key)
    if isinstance(value, str):
        return value
    return None
