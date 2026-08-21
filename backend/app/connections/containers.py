"""Dependency-injector container for connections bounded context."""

from __future__ import annotations

from app.connections.application.librarian_service import LibrarianService
from app.connections.application.librarians.oauth_service import LibrarianOAuthService
from app.connections.infrastructure.librarians.clients import LibrarianClientFactory
from app.connections.infrastructure.librarians.oauth.openai_codex_oauth_adapter import (
    OpenAICodexOAuthClient,
)
from app.connections.infrastructure.repositories.librarian_repository import (
    ProviderSecretRepository,
    SqlAlchemyLibrarianProviderRepository,
)
from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession


class ConnectionsContainer(containers.DeclarativeContainer):
    """Container for external provider connections and credential state."""

    db_session = providers.Dependency(instance_of=AsyncSession)
    secret_cipher = providers.Dependency()
    librarian_provider_repo = providers.Factory(
        SqlAlchemyLibrarianProviderRepository,
        session=db_session,
        secret_cipher=secret_cipher,
    )
    provider_secret_repo = providers.Factory(
        ProviderSecretRepository,
        session=db_session,
        secret_cipher=secret_cipher,
    )
    openai_codex_oauth_client = providers.Factory(OpenAICodexOAuthClient)
    librarian_client_factory = providers.Factory(LibrarianClientFactory)
    librarian_service = providers.Factory(
        LibrarianService,
        provider_repo=librarian_provider_repo,
        secret_repo=provider_secret_repo,
        client_factory=librarian_client_factory,
    )
    librarian_oauth_service = providers.Factory(
        LibrarianOAuthService,
        provider_repo=librarian_provider_repo,
        secret_repo=provider_secret_repo,
        oauth_client=openai_codex_oauth_client,
    )
