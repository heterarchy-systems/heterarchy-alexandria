"""Execution-readiness policy for librarian providers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import (
    AuthType,
    ProviderSecretKey,
    ProviderType,
)
from app.connections.domain.repositories.librarian_repository import (
    IProviderSecretRepository,
)
from app.shared.exceptions.common_exceptions import BoundaryValidationError
from app.shared.types.types_convert_utils import (
    aware_utc_datetime,
    enum_value,
    now_utc,
    optional_iso_utc_datetime,
)


async def provider_can_execute(
    provider: LibrarianProvider,
    secret_repo: IProviderSecretRepository,
    now_provider: Callable[[], datetime] = now_utc,
) -> bool:
    """Return whether a provider has enough credential material to execute.

    Args:
        provider: Provider metadata row.
        secret_repo: Provider secret repository.
        now_provider: Clock boundary for deterministic tests.

    Returns:
        bool: ``True`` when the provider can execute or refresh a request.
    """
    if not provider.enabled:
        return False
    provider_shape = _provider_shape(provider)
    if provider_shape is None:
        return False
    provider_type, auth_type = provider_shape
    if provider_type is ProviderType.OPENAI and auth_type is AuthType.API_KEY:
        return await _has_secret(secret_repo, provider.id, ProviderSecretKey.API_KEY)
    if provider_type is ProviderType.OPENAI_CODEX and auth_type is AuthType.OAUTH:
        return await _has_oauth_execution_secret(provider, secret_repo, now_provider)
    return False


async def _has_oauth_execution_secret(
    provider: LibrarianProvider,
    secret_repo: IProviderSecretRepository,
    now_provider: Callable[[], datetime],
) -> bool:
    refresh_token = await _resolve_secret(
        secret_repo,
        provider.id,
        ProviderSecretKey.OAUTH_REFRESH_TOKEN,
    )
    if refresh_token is not None:
        return True
    access_token = await _resolve_secret(
        secret_repo,
        provider.id,
        ProviderSecretKey.OAUTH_ACCESS_TOKEN,
    )
    if access_token is None:
        return False
    expires_at = optional_iso_utc_datetime(
        await _resolve_secret(
            secret_repo,
            provider.id,
            ProviderSecretKey.OAUTH_EXPIRES_AT,
        )
    )
    if expires_at is None:
        return False
    current = _aware_now(now_provider)
    return expires_at > current


async def _has_secret(
    secret_repo: IProviderSecretRepository,
    provider_id: str,
    key: ProviderSecretKey,
) -> bool:
    value = await _resolve_secret(secret_repo, provider_id, key)
    return value is not None


async def _resolve_secret(
    secret_repo: IProviderSecretRepository,
    provider_id: str,
    key: ProviderSecretKey,
) -> str | None:
    value = await secret_repo.resolve(provider_id, key.value)
    if value is None or value == "":
        return None
    return value


def _provider_shape(
    provider: LibrarianProvider,
) -> tuple[ProviderType, AuthType] | None:
    try:
        provider_type = enum_value(
            provider.provider_type, ProviderType, "provider_type"
        )
        auth_type = enum_value(provider.auth_type, AuthType, "auth_type")
    except BoundaryValidationError:
        return None
    return provider_type, auth_type


def _aware_now(now_provider: Callable[[], datetime]) -> datetime:
    current = now_provider()
    return aware_utc_datetime(current)
