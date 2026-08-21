"""Configured external provider adapter for memory relation proposals."""

from __future__ import annotations

from app.connections.domain.event_enum.provider_enums import (
    AuthType,
    ProviderSecretKey,
    ProviderType,
)
from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.connections.infrastructure.librarians.openai_adapter import (
    OpenAIClientBuilder,
    OpenAIClientConfig,
    build_openai_client,
)
from app.connections.infrastructure.librarians.openai_execution_support import (
    OpenAICodexClientConfigBuilder,
    string_config_value,
)
from app.connections.infrastructure.librarians.provider_types import (
    parse_auth_type,
    parse_provider_type,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemoryRecallCandidate,
)
from app.memory.domain.entities.memory_relation_proposal import (
    MemoryRelationModelProposal,
)
from app.memory.domain.repositories.contexts.memory_relation_proposal_provider import (
    IMemoryRelationProposalProvider,
)
from app.memory.infrastructure.providers.openai_memory_relation_proposal_provider import (
    OpenAIMemoryRelationProposalProvider,
    OpenAIResponseFetcher,
    fetch_openai_relation_proposal,
)
from app.operations.application.readiness.external_api_rate_limit import (
    ExternalApiRateLimiter,
    ExternalApiRateLimitError,
    NoopExternalApiRateLimiter,
)
from app.shared.exceptions.connections_exceptions import ConnectionsDomainError
from openai import OpenAIError
from sqlalchemy.exc import SQLAlchemyError


class ConfiguredMemoryRelationProposalProvider(IMemoryRelationProposalProvider):
    """Resolve one explicitly configured encrypted provider for relation proposals."""

    def __init__(
        self,
        provider_repo: ILibrarianProviderRepository,
        secret_repo: IProviderSecretRepository,
        provider_id: str | None,
        default_model: str,
        timeout_seconds: float,
        openai_client_builder: OpenAIClientBuilder = build_openai_client,
        response_fetcher: OpenAIResponseFetcher = fetch_openai_relation_proposal,
        rate_limiter: ExternalApiRateLimiter | None = None,
    ) -> None:
        self._provider_repo = provider_repo
        self._secret_repo = secret_repo
        self._provider_id = _normalized_optional(provider_id)
        self._default_model = default_model.strip()
        self._timeout_seconds = timeout_seconds
        self._openai_client_builder = openai_client_builder
        self._response_fetcher = response_fetcher
        self._codex_config_builder = OpenAICodexClientConfigBuilder(secret_repo)
        self._rate_limiter = rate_limiter or NoopExternalApiRateLimiter()

    async def propose(
        self,
        candidate: MemoryCandidate,
        existing: MemoryRecallCandidate,
    ) -> MemoryRelationModelProposal | None:
        """Propose only when an enabled provider and usable secret are configured.

        Args:
            candidate: Candidate.
            existing: Existing.

        Returns:
            MemoryRelationModelProposal | None: Operation result.
        """
        provider_id = self._provider_id
        if provider_id is None:
            return None
        try:
            provider = await self._provider_repo.get(provider_id)
            if provider is None or not provider.enabled:
                return None
            provider_type = parse_provider_type(provider.provider_type)
            auth_type = parse_auth_type(provider.auth_type)
            client_config = await self._client_config(
                provider_id=provider.id,
                provider_type=provider_type,
                auth_type=auth_type,
            )
            if client_config is None:
                return None
            await self._rate_limiter.acquire(
                _provider_scope(provider_type),
                f"memory-relation:{provider.id}",
            )
            client = self._openai_client_builder(client_config)
            model = string_config_value(provider.config.get("model"))
            proposal_provider = OpenAIMemoryRelationProposalProvider(
                client=client,
                model=model or self._default_model,
                response_fetcher=self._response_fetcher,
            )
            return await proposal_provider.propose(candidate, existing)
        except (
            ConnectionsDomainError,
            ExternalApiRateLimitError,
            OpenAIError,
            SQLAlchemyError,
            ValueError,
        ):
            return None

    async def _client_config(
        self,
        provider_id: str,
        provider_type: ProviderType | None,
        auth_type: AuthType,
    ) -> OpenAIClientConfig | None:
        if provider_type is ProviderType.OPENAI and auth_type is AuthType.API_KEY:
            api_key = await self._secret_repo.resolve(
                provider_id,
                ProviderSecretKey.API_KEY.value,
            )
            if not api_key:
                return None
            return OpenAIClientConfig(
                api_key=api_key,
                timeout=self._timeout_seconds,
            )
        if provider_type is ProviderType.OPENAI_CODEX and auth_type is AuthType.OAUTH:
            return await self._codex_config_builder.build(
                provider_id=provider_id,
                timeout=self._timeout_seconds,
            )
        return None


def _normalized_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _provider_scope(provider_type: ProviderType | None) -> str:
    if provider_type is None:
        return "openai-compatible"
    return provider_type.value
