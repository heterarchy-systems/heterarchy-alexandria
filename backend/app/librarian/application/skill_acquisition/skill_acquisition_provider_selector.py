"""Provider selection policy for durable skill-acquisition jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import ProviderType
from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.librarian.application.delegation.provider_execution_policy import (
    provider_can_execute,
)


class SkillAcquisitionProviderSelector:
    """Resolve requested or first executable providers for skill acquisition."""

    def __init__(
        self,
        provider_repository: ILibrarianProviderRepository,
        credential_repository: IProviderSecretRepository,
        now_provider: Callable[[], datetime],
    ) -> None:
        """Initialize provider selection dependencies.

        Args:
            provider_repository: Librarian provider settings repository.
            credential_repository: Encrypted provider credential repository.
            now_provider: Clock boundary for credential expiry checks.
        """
        self._provider_repository = provider_repository
        self._credential_repository = credential_repository
        self._now_provider = now_provider

    async def select(self, provider_id: str | None) -> LibrarianProvider | None:
        """Return a requested provider or the first executable provider.

        Args:
            provider_id: Optional explicit provider identifier.

        Returns:
            Selected provider when one is available.
        """
        if provider_id is not None:
            return await self._provider_repository.get(provider_id)
        providers = await self._provider_repository.list_all()
        executable = [
            provider for provider in providers if await self.is_executable(provider)
        ]
        for provider in executable:
            if provider.provider_type is ProviderType.OPENAI:
                return provider
        return executable[0] if executable else None

    async def is_executable(self, provider: LibrarianProvider) -> bool:
        """Return whether one provider can execute with current credentials.

        Args:
            provider: Provider candidate to evaluate.

        Returns:
            Whether the provider is executable now.
        """
        return await provider_can_execute(
            provider,
            self._credential_repository,
            self._now_provider,
        )
