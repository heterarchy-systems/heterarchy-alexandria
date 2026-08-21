"""Execution-ready provider selection for Hermes librarian collaboration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.librarian.application.delegation.provider_execution_policy import (
    provider_can_execute,
)


class HermesCollaborationProviderSelector:
    """Return librarian providers that can execute with current credentials."""

    def __init__(
        self,
        provider_repository: ILibrarianProviderRepository,
        credential_repository: IProviderSecretRepository,
        now_provider: Callable[[], datetime],
    ) -> None:
        """Initialize provider readiness dependencies.

        Args:
            provider_repository: Librarian provider settings repository.
            credential_repository: Encrypted provider credential repository.
            now_provider: Clock boundary for credential expiry checks.
        """
        self._provider_repository = provider_repository
        self._credential_repository = credential_repository
        self._now_provider = now_provider

    async def list_execution_ready(self) -> list[LibrarianProvider]:
        """Return enabled and authorized providers in repository order.

        Returns:
            Providers currently able to execute librarian delegation.
        """
        providers = await self._provider_repository.list_all()
        return [
            provider
            for provider in providers
            if await provider_can_execute(
                provider,
                self._credential_repository,
                self._now_provider,
            )
        ]
