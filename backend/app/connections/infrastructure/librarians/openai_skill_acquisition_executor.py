"""Provider-backed OpenAI/Codex skill-acquisition executor."""

from __future__ import annotations

import logging

import anyio
from app.connections.domain.entities.read_models import LibrarianProvider
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
    OpenAIResponseSummaryFetcher,
    positive_float_config_value,
    string_config_value,
)
from app.connections.infrastructure.librarians.openai_skill_acquisition_artifact_parser import (
    skill_acquisition_artifact_from_provider_text,
)
from app.connections.infrastructure.librarians.provider_types import (
    parse_auth_type,
    parse_provider_type,
)
from app.librarian.application.skill_acquisition.skill_acquisition_runner import (
    SkillAcquisitionExecutionRequest,
)
from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
)
from app.operations.application.readiness.external_api_rate_limit import (
    ExternalApiRateLimiter,
    ExternalApiRateLimitError,
    NoopExternalApiRateLimiter,
)
from app.shared.exceptions.librarian_exceptions import (
    LibrarianSkillAcquisitionExecutionError,
    LibrarianSkillAcquisitionProviderError,
)
from asyncer import asyncify
from openai import OpenAIError

_DEFAULT_MODEL = "gpt-5.5"
_DEFAULT_SKILL_ACQUISITION_TIMEOUT_SECONDS = 120.0
_SKILL_ACQUISITION_TIMEOUT_CONFIG_KEY = "skill_acquisition_timeout_seconds"
_DEFAULT_INSTRUCTIONS = """
Research the requested capability before drafting the skill. When web search is
available, prefer official documentation, primary repositories, standards, and
first-party examples. Use current sources and distinguish verified behavior from
inference.

Return only strict JSON with these fields:
title, purpose, content, summary, tags, required_tools, evidence_urls,
evidence_items, source_summary, next_steps, risk_level, version, activate, status.
Each evidence_items object must include url_or_path, title, source_kind,
publisher_or_repository, accessed_at, supports_claims, freshness, and notes.
Use opened source metadata only; do not invent evidence. If evidence is
insufficient, set status to NEEDS_REVIEW and explain the gap in next_steps.
Do not include markdown fences, explanations, or extra prose.
""".strip()
logger = logging.getLogger(__name__)
_SUMMARY_FETCHER = OpenAIResponseSummaryFetcher(strip_text_response=False)


class OpenAISkillAcquisitionExecutor:
    """Execute skill-acquisition prompts via OpenAI-style provider responses API."""

    def __init__(
        self,
        provider_repo: ILibrarianProviderRepository,
        secret_repo: IProviderSecretRepository,
        openai_client_builder: OpenAIClientBuilder = build_openai_client,
        rate_limiter: ExternalApiRateLimiter | None = None,
    ) -> None:
        """Initialize provider-backed skill-acquisition executor.

        Args:
            provider_repo: Provider metadata repository.
            secret_repo: Provider secret resolver.
            openai_client_builder: SDK client builder boundary.
        """
        self.provider_repo = provider_repo
        self.secret_repo = secret_repo
        self._codex_config_builder = OpenAICodexClientConfigBuilder(secret_repo)
        self.openai_client_builder = openai_client_builder
        self._rate_limiter = rate_limiter or NoopExternalApiRateLimiter()

    async def acquire_skill(
        self,
        request: SkillAcquisitionExecutionRequest,
    ) -> SkillAcquisitionArtifact:
        """Acquire one skill artifact from a configured provider.

        Args:
            request: Normalized acquisition request.

        Returns:
            Parsed and validated skill artifact.
        """
        provider = await self._resolve_provider(request)
        provider_type = _parse_provider_type(provider)
        auth_type = _parse_auth_type(provider)
        client_config = await self._client_config(provider, provider_type, auth_type)
        if client_config is None:
            raise LibrarianSkillAcquisitionProviderError(
                "Provider credentials unavailable for skill acquisition"
            )

        client = self.openai_client_builder(client_config)
        model = _model_for_provider(provider)
        instructions = _acquisition_instructions()
        timeout_seconds = _skill_acquisition_timeout_seconds(provider)
        try:
            await self._rate_limiter.acquire(
                _provider_scope(provider_type),
                f"skill-acquisition:{provider.id}",
            )
            with anyio.fail_after(timeout_seconds):
                if provider_type is ProviderType.OPENAI_CODEX:
                    summary = await asyncify(
                        _SUMMARY_FETCHER.fetch_codex_stream_summary,
                        abandon_on_cancel=True,
                    )(
                        client,
                        model,
                        request.prompt,
                        instructions,
                    )
                else:
                    summary = await asyncify(
                        _SUMMARY_FETCHER.fetch_openai_summary,
                        abandon_on_cancel=True,
                    )(
                        client,
                        model,
                        request.prompt,
                        instructions,
                        enable_web_search=True,
                    )
        except TimeoutError as error:
            _log_provider_timeout(
                provider_id=provider.id,
                provider_type=provider_type,
                timeout_seconds=timeout_seconds,
            )
            raise LibrarianSkillAcquisitionExecutionError(
                "Skill acquisition execution timed out"
            ) from error
        except (ExternalApiRateLimitError, OpenAIError) as error:
            _log_provider_execution_failure(
                provider_id=provider.id,
                provider_type=provider_type,
                error=error,
            )
            raise LibrarianSkillAcquisitionExecutionError(
                "Skill acquisition execution failed"
            ) from error

        return skill_acquisition_artifact_from_provider_text(summary)

    async def _resolve_provider(
        self,
        request: SkillAcquisitionExecutionRequest,
    ) -> LibrarianProvider:
        """Resolve provider id and ensure it exists.

        Args:
            request: Execution request that references a provider.

        Returns:
            Matching provider read model.
        """
        if request.provider_id is None:
            raise LibrarianSkillAcquisitionProviderError(
                "Skill acquisition requires a provider id"
            )
        provider = await self.provider_repo.get(request.provider_id)
        if provider is None:
            raise LibrarianSkillAcquisitionProviderError(
                "Provider not found for skill acquisition"
            )
        return provider

    async def _client_config(
        self,
        provider: LibrarianProvider,
        provider_type: ProviderType | None,
        auth_type: AuthType,
    ) -> OpenAIClientConfig | None:
        if provider_type is ProviderType.OPENAI and auth_type is AuthType.API_KEY:
            api_key = await self.secret_repo.resolve(
                provider.id,
                ProviderSecretKey.API_KEY.value,
            )
            if not api_key:
                return None
            return OpenAIClientConfig(
                api_key=api_key,
                timeout=_skill_acquisition_timeout_seconds(provider),
            )

        if provider_type is ProviderType.OPENAI_CODEX and auth_type is AuthType.OAUTH:
            return await self._codex_client_config(provider)

        return None

    async def _codex_client_config(
        self,
        provider: LibrarianProvider,
    ) -> OpenAIClientConfig | None:
        client_config = await self._codex_config_builder.build(
            provider_id=provider.id,
            timeout=_skill_acquisition_timeout_seconds(provider),
        )
        return client_config


def _parse_provider_type(provider: LibrarianProvider) -> ProviderType:
    provider_type = parse_provider_type(provider.provider_type)
    if provider_type not in {ProviderType.OPENAI, ProviderType.OPENAI_CODEX}:
        raise LibrarianSkillAcquisitionProviderError(
            "Provider type is unsupported for skill acquisition"
        )
    return provider_type


def _provider_scope(provider_type: ProviderType) -> str:
    return provider_type.value


def _parse_auth_type(provider: LibrarianProvider) -> AuthType:
    try:
        auth_type = parse_auth_type(provider.auth_type)
    except ValueError as error:
        raise LibrarianSkillAcquisitionProviderError(
            "Provider auth type is unsupported for skill acquisition"
        ) from error
    if auth_type not in {AuthType.API_KEY, AuthType.OAUTH}:
        raise LibrarianSkillAcquisitionProviderError(
            "Provider auth type is unsupported for skill acquisition"
        )
    return auth_type


def _model_for_provider(provider: LibrarianProvider) -> str:
    model = string_config_value(provider.config.get("model"))
    if model is None:
        return _DEFAULT_MODEL
    return model


def _acquisition_instructions() -> str:
    return _DEFAULT_INSTRUCTIONS


def _skill_acquisition_timeout_seconds(provider: LibrarianProvider) -> float:
    value = provider.config.get(_SKILL_ACQUISITION_TIMEOUT_CONFIG_KEY)
    timeout_seconds = positive_float_config_value(value)
    if timeout_seconds is None:
        return _DEFAULT_SKILL_ACQUISITION_TIMEOUT_SECONDS
    return timeout_seconds


def _log_provider_timeout(
    provider_id: str,
    provider_type: ProviderType | None,
    timeout_seconds: float,
) -> None:
    logger.warning(
        "Skill acquisition provider execution timed out",
        extra={
            "provider_id": provider_id,
            "provider_type": None if provider_type is None else provider_type.value,
            "timeout_seconds": timeout_seconds,
        },
    )


def _log_provider_execution_failure(
    provider_id: str,
    provider_type: ProviderType | None,
    error: Exception,
) -> None:
    logger.warning(
        "Skill acquisition provider execution failed",
        extra={
            "provider_id": provider_id,
            "provider_type": None if provider_type is None else provider_type.value,
            "error_type": type(error).__name__,
        },
    )
