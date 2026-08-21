"""Librarian provider connection-test application service."""

from __future__ import annotations

from app.connections.domain.contracts.librarian_client_contracts import (
    LibrarianProviderClientFactory,
)
from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.connections.domain.types.librarian_provider_payload_types import (
    LibrarianProviderTestPayload,
)
from app.shared.exceptions.connections_exceptions import (
    ConnectionsResourceNotFoundError,
)


class ProviderConnectionTestService:
    """Verify one provider registration through its configured client adapter."""

    def __init__(
        self,
        provider_repository: ILibrarianProviderRepository,
        credential_repository: IProviderSecretRepository,
        client_factory: LibrarianProviderClientFactory,
    ) -> None:
        """Create the provider connection-test service.

        Args:
            provider_repository: Provider persistence port.
            credential_repository: Encrypted provider credential repository.
            client_factory: Provider test client factory.
        """
        self._provider_repository = provider_repository
        self._credential_repository = credential_repository
        self._client_factory = client_factory

    async def test(
        self,
        provider_id: str,
        test_query: str,
    ) -> LibrarianProviderTestPayload:
        """Execute one provider connection test.

        Args:
            provider_id: Provider identifier.
            test_query: Text submitted for a dry run.

        Returns:
            Public connection-test result.
        """
        model = await self._provider_repository.get(provider_id)
        if model is None:
            raise ConnectionsResourceNotFoundError(f"Provider not found: {provider_id}")
        result = await self._client_factory.test_connection(
            provider=model,
            secret_resolver=self._credential_repository,
            test_query=test_query,
        )
        return result.as_public_dict()
