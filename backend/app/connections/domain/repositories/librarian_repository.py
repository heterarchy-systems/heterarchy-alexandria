"""Librarian provider repository abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.connections.domain.contracts.librarian_provider_contracts import (
    LibrarianProviderCreate,
    LibrarianProviderUpdate,
)
from app.connections.domain.entities.read_models import LibrarianProvider


class ILibrarianProviderRepository(ABC):
    """Persistence contract for librarian provider settings."""

    @abstractmethod
    async def create(self, payload: LibrarianProviderCreate) -> LibrarianProvider:
        """Create a provider entry.

        Args:
            payload [LibrarianProviderCreate]: Value supplied to create.

        Returns:
            LibrarianProvider: Value produced by create.
        """

    @abstractmethod
    async def get(self, provider_id: str) -> LibrarianProvider | None:
        """Get one provider.

        Args:
            provider_id [str]: Value supplied to get.

        Returns:
            LibrarianProvider | None: Value produced by get.
        """

    @abstractmethod
    async def list_all(self) -> list[LibrarianProvider]:
        """List all providers.

        Returns:
            list[LibrarianProvider]: Value produced by list_all.
        """

    @abstractmethod
    async def update(
        self, provider_id: str, payload: LibrarianProviderUpdate
    ) -> LibrarianProvider:
        """Patch provider settings.

        Args:
            provider_id [str]: Value supplied to update.
            payload [LibrarianProviderUpdate]: Value supplied to update.

        Returns:
            LibrarianProvider: Value produced by update.
        """

    @abstractmethod
    async def delete(self, provider_id: str) -> None:
        """Delete one provider.

        Args:
            provider_id [str]: Value supplied to delete.
        """


class IProviderSecretRepository(ABC):
    """Persistence contract for librarian provider secrets."""

    @abstractmethod
    async def resolve(self, provider_id: str, key_name: str) -> str | None:
        """Return secret value by key name.

        Args:
            provider_id [str]: Value supplied to resolve.
            key_name [str]: Value supplied to resolve.

        Returns:
            str | None: Value produced by resolve.
        """

    @abstractmethod
    async def set_secret(self, provider_id: str, key_name: str, value: str) -> None:
        """Persist or update one provider secret.

        Args:
            provider_id [str]: Value supplied to set_secret.
            key_name [str]: Value supplied to set_secret.
            value [str]: Value supplied to set_secret.
        """

    @abstractmethod
    async def delete_for_provider(self, provider_id: str, key_name: str) -> None:
        """Delete one provider secret key.

        Args:
            provider_id [str]: Value supplied to delete_for_provider.
            key_name [str]: Value supplied to delete_for_provider.
        """
