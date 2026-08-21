"""Agent preferred-provider resolution and execution policy."""

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
from app.shared.exceptions.librarian_exceptions import (
    LibrarianProviderUnsupportedError,
    LibrarianResourceNotFoundError,
)


class AgentProviderAssignmentPolicy:
    """Resolve and validate preferred providers assigned to agent profiles."""

    def __init__(
        self,
        provider_repository: ILibrarianProviderRepository,
        credential_repository: IProviderSecretRepository,
        now_provider: Callable[[], datetime],
    ) -> None:
        """Create the preferred-provider policy.

        Args:
            provider_repository: Librarian provider repository.
            credential_repository: Encrypted provider credential repository.
            now_provider: Clock boundary for executable checks.
        """
        self._provider_repository = provider_repository
        self._credential_repository = credential_repository
        self._now_provider = now_provider

    async def ensure_executable(self, provider_id: str | None) -> None:
        """Reject profile assignments to non-executable providers.

        Args:
            provider_id: Preferred librarian provider id or provider name.
        """
        if provider_id is None:
            return
        provider = await self._resolve(provider_id)
        if provider is None:
            raise LibrarianResourceNotFoundError(f"Provider not found: {provider_id}")
        executable = await provider_can_execute(
            provider,
            self._credential_repository,
            self._now_provider,
        )
        if not executable:
            raise LibrarianProviderUnsupportedError(
                f"Provider is not authorized for librarian execution: {provider_id}"
            )

    async def _resolve(self, provider_id: str) -> LibrarianProvider | None:
        provider = await self._provider_repository.get(provider_id)
        if provider is not None:
            return provider
        providers = await self._provider_repository.list_all()
        return next(
            (candidate for candidate in providers if candidate.name == provider_id),
            None,
        )
