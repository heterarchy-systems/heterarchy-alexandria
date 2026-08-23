"""Librarian provider repository implementation."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections.domain.contracts.librarian_provider_contracts import (
    LibrarianProviderCreate,
    LibrarianProviderUpdate,
)
from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import AuthType, ProviderType
from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository as IProviderSecretRepositoryPort,
)
from app.connections.infrastructure.models.librarian_provider_models import (
    LibrarianProviderORM,
    ProviderSecretORM,
)
from app.shared.exceptions.connections_exceptions import (
    ConnectionsResourceNotFoundError,
)
from app.shared.security.secret_cipher import SecretCipher, SecretCipherSettings
from app.shared.types.types_convert_utils import aware_utc_datetime

logger = logging.getLogger(__name__)


def _to_read_model(row: LibrarianProviderORM) -> LibrarianProvider:
    """Map a librarian provider ORM row into the domain read model.

    Args:
        row: Row used by this operation.

    Returns:
        LibrarianProvider result produced by to read model.
    """
    return LibrarianProvider(
        id=row.id,
        name=row.name,
        provider_type=ProviderType(row.provider_type),
        auth_type=AuthType(row.auth_type),
        enabled=row.enabled,
        config=row.config,
        created_at=aware_utc_datetime(row.created_at),
        updated_at=aware_utc_datetime(row.updated_at),
    )


class SqlAlchemyLibrarianProviderRepository(ILibrarianProviderRepository):
    """Persistence for librarian provider configuration."""

    def __init__(
        self, session: AsyncSession, secret_cipher: SecretCipher | None = None
    ) -> None:
        """Initialize repository.

        Args:
            session: Active async session.
            secret_cipher: Cipher for encrypting optional secret payloads.
        """
        self._session = session
        self._secret_cipher = (
            SecretCipher.from_settings(SecretCipherSettings())
            if secret_cipher is None
            else secret_cipher
        )

    async def create(self, payload: LibrarianProviderCreate) -> LibrarianProvider:
        """Create provider and optional secret records.

        Args:
            payload [LibrarianProviderCreate]: Value supplied to create.

            payload: Validated payload for this operation.
        Returns:
            LibrarianProvider: Value produced by create.
        """
        model = LibrarianProviderORM(**payload.to_record())
        self._session.add(model)
        await self._session.flush()
        return _to_read_model(model)

    async def get(self, provider_id: str) -> LibrarianProvider | None:
        """Get one provider by id.

        Args:
            provider_id [str]: Value supplied to get.

            provider_id: Identifier for provider.
        Returns:
            LibrarianProvider | None: Value produced by get.
        """
        model = await self._session.get(LibrarianProviderORM, provider_id)
        return None if model is None else _to_read_model(model)

    async def list_all(self) -> list[LibrarianProvider]:
        """List all provider records.

        Returns:
            list[LibrarianProvider]: Value produced by list_all.
        """
        rows = await self._session.execute(select(LibrarianProviderORM))
        return [_to_read_model(row) for row in rows.scalars().all()]

    async def update(
        self,
        provider_id: str,
        payload: LibrarianProviderUpdate,
    ) -> LibrarianProvider:
        """Patch provider fields and secret values.

        Args:
            provider_id [str]: Value supplied to update.
            payload [LibrarianProviderUpdate]: Value supplied to update.

            provider_id: Identifier for provider.
            payload: Validated payload for this operation.
        Returns:
            LibrarianProvider: Value produced by update.
        """
        model = await self._session.get(LibrarianProviderORM, provider_id)
        if model is None:
            raise ConnectionsResourceNotFoundError(f"Provider not found: {provider_id}")

        values = payload.to_record()
        if "name" in values:
            model.name = values["name"]
        if "provider_type" in values:
            model.provider_type = values["provider_type"]
        if "auth_type" in values:
            model.auth_type = values["auth_type"]
        if "enabled" in values:
            model.enabled = values["enabled"]
        if "config" in values:
            model.config = values["config"]
        model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return _to_read_model(model)

    async def delete(self, provider_id: str) -> None:
        """Delete provider and dependent secrets.

        Args:
            provider_id [str]: Value supplied to delete.
            provider_id: Identifier for provider.
        """
        model = await self._session.get(LibrarianProviderORM, provider_id)
        if model is None:
            raise ConnectionsResourceNotFoundError(f"Provider not found: {provider_id}")

        await self._session.execute(
            delete(LibrarianProviderORM).where(LibrarianProviderORM.id == provider_id)
        )
        await self._session.flush()


class ProviderSecretRepository(IProviderSecretRepositoryPort):
    """Separate access to secret records for test and redaction safety."""

    def __init__(
        self, session: AsyncSession, secret_cipher: SecretCipher | None = None
    ) -> None:
        """Initialize secret repository.

        Args:
            session: Active async session.
            secret_cipher: Cipher used to decrypt/encrypt values.
        """
        self._session = session
        self._secret_cipher = (
            SecretCipher.from_settings(SecretCipherSettings())
            if secret_cipher is None
            else secret_cipher
        )

    async def resolve(self, provider_id: str, key_name: str) -> str | None:
        """Return secret value by key name.

        Args:
            provider_id [str]: Value supplied to resolve.
            key_name [str]: Value supplied to resolve.

            provider_id: Identifier for provider.
            key_name: Key name used by this operation.
        Returns:
            str | None: Value produced by resolve.
        """
        query = select(ProviderSecretORM.value).where(
            ProviderSecretORM.provider_id == provider_id,
            ProviderSecretORM.key_name == key_name,
        )
        value = await self._session.scalar(query)
        if value is None:
            return None
        try:
            return self._secret_cipher.decrypt(value)
        except ValueError:
            logger.warning(
                "Provider secret failed decryption and will be treated as missing",
                extra={"provider_id": provider_id, "key_name": key_name},
            )
            return None

    async def set_secret(self, provider_id: str, key_name: str, value: str) -> None:
        """Upsert one provider secret by key.

        Args:
            provider_id [str]: Value supplied to set_secret.
            key_name [str]: Value supplied to set_secret.
            value [str]: Value supplied to set_secret.
            provider_id: Identifier for provider.
            key_name: Key name used by this operation.
            value: Value being processed.
        """
        existing = await self._session.scalar(
            select(ProviderSecretORM).where(
                ProviderSecretORM.provider_id == provider_id,
                ProviderSecretORM.key_name == key_name,
            )
        )
        encrypted_value = self._secret_cipher.encrypt(value)
        if existing is None:
            self._session.add(
                ProviderSecretORM(
                    provider_id=provider_id,
                    key_name=key_name,
                    value=encrypted_value,
                )
            )
        else:
            existing.value = encrypted_value
        await self._session.flush()

    async def delete_for_provider(self, provider_id: str, key_name: str) -> None:
        """Delete one secret key from a provider.

        Args:
            provider_id [str]: Value supplied to delete_for_provider.
            key_name [str]: Value supplied to delete_for_provider.
            provider_id: Identifier for provider.
            key_name: Key name used by this operation.
        """
        await self._session.execute(
            delete(ProviderSecretORM).where(
                ProviderSecretORM.provider_id == provider_id,
                ProviderSecretORM.key_name == key_name,
            )
        )
        await self._session.flush()
