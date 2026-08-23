"""Encrypted OAuth credential persistence boundary."""

from __future__ import annotations

from datetime import datetime

from app.connections.domain.contracts.librarian_oauth_contracts import (
    OAuthDeviceAuthorization,
    OAuthTokenSet,
)
from app.connections.domain.event_enum.provider_enums import ProviderSecretKey
from app.connections.domain.repositories.librarian_repository import (
    IProviderSecretRepository,
)
from app.shared.types.types_convert_utils import (
    aware_utc_datetime,
    optional_iso_utc_datetime,
)

DEVICE_FLOW_SECRET_KEYS: tuple[ProviderSecretKey, ...] = (
    ProviderSecretKey.OAUTH_DEVICE_CODE,
    ProviderSecretKey.OAUTH_DEVICE_EXPIRES_AT,
    ProviderSecretKey.OAUTH_POLL_INTERVAL_SECONDS,
)
ALL_PROVIDER_SECRET_KEYS: tuple[ProviderSecretKey, ...] = tuple(ProviderSecretKey)


class LibrarianOAuthSecretStore:
    """Persist and resolve OAuth credentials without exposing raw repository keys."""

    def __init__(self, repository: IProviderSecretRepository) -> None:
        """Create the encrypted credential boundary.

        Args:
            repository: Encrypted provider secret repository.
        """
        self._repository = repository

    async def resolve(
        self,
        provider_id: str,
        key: ProviderSecretKey,
    ) -> str | None:
        """Resolve one encrypted provider credential.

        Args:
            provider_id: Provider identifier.
            key: Credential key.

        Returns:
            Decrypted credential when present.
        """
        return await self._repository.resolve(provider_id, key.value)

    async def delete(
        self,
        provider_id: str,
        keys: tuple[ProviderSecretKey, ...],
    ) -> None:
        """Delete selected credentials for one provider.

        Args:
            provider_id: Provider identifier.
            keys: Credential keys to delete.
        """
        for key in keys:
            await self._repository.delete_for_provider(provider_id, key.value)

    async def delete_all(self, provider_id: str) -> None:
        """Delete every known OAuth credential for one provider.

        Args:
            provider_id: Provider identifier.
        """
        await self.delete(provider_id, ALL_PROVIDER_SECRET_KEYS)

    async def store_device_authorization(
        self,
        provider_id: str,
        authorization: OAuthDeviceAuthorization,
    ) -> None:
        """Persist one device-flow authorization response.

        Args:
            provider_id: Provider identifier.
            authorization: Device authorization returned by the provider.
        """
        await _set_secret(
            self._repository,
            provider_id,
            ProviderSecretKey.OAUTH_DEVICE_CODE,
            authorization.device_code,
        )
        await _set_secret(
            self._repository,
            provider_id,
            ProviderSecretKey.OAUTH_DEVICE_EXPIRES_AT,
            _format_datetime(authorization.expires_at),
        )
        await _set_secret(
            self._repository,
            provider_id,
            ProviderSecretKey.OAUTH_POLL_INTERVAL_SECONDS,
            str(authorization.interval_seconds),
        )

    async def store_token_set(
        self,
        provider_id: str,
        token_set: OAuthTokenSet,
    ) -> None:
        """Persist an OAuth token set without exposing token material.

        Args:
            provider_id: Provider identifier.
            token_set: Access and optional refresh token payload.
        """
        await _set_secret(
            self._repository,
            provider_id,
            ProviderSecretKey.OAUTH_ACCESS_TOKEN,
            token_set.access_token,
        )
        if token_set.refresh_token is not None:
            await _set_secret(
                self._repository,
                provider_id,
                ProviderSecretKey.OAUTH_REFRESH_TOKEN,
                token_set.refresh_token,
            )
        await _set_secret(
            self._repository,
            provider_id,
            ProviderSecretKey.OAUTH_EXPIRES_AT,
            _format_datetime(token_set.expires_at),
        )
        await _set_secret(
            self._repository,
            provider_id,
            ProviderSecretKey.OAUTH_TOKEN_TYPE,
            token_set.token_type,
        )
        if token_set.scope is not None:
            await _set_secret(
                self._repository,
                provider_id,
                ProviderSecretKey.OAUTH_SCOPE,
                token_set.scope,
            )

    async def expires_at(
        self,
        provider_id: str,
        key: ProviderSecretKey,
    ) -> datetime | None:
        """Resolve one persisted OAuth expiry timestamp.

        Args:
            provider_id: Provider identifier.
            key: Expiry credential key.

        Returns:
            Parsed aware UTC timestamp when present.
        """
        value = await self.resolve(provider_id, key)
        return optional_iso_utc_datetime(value)


async def _set_secret(
    repository: IProviderSecretRepository,
    provider_id: str,
    key: ProviderSecretKey,
    value: str,
) -> None:
    """Execute set secret.

    Args:
        repository: Repository used by this operation.
        provider_id: Identifier for provider.
        key: Key used by this operation.
        value: Value being processed.
    """
    await repository.set_secret(
        provider_id=provider_id,
        key_name=key.value,
        value=value,
    )


def _format_datetime(value: datetime) -> str:
    """Format datetime.

    Args:
        value: Value being processed.

    Returns:
        Formatted datetime.
    """
    return aware_utc_datetime(value).isoformat()
