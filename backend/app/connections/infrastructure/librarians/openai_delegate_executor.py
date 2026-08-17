"""Provider-backed OpenAI/Codex librarian delegate executor."""

from __future__ import annotations

import logging
from dataclasses import replace

from app.connections.domain.event_enum.provider_enums import (
    AuthType,
    ProviderSecretKey,
    ProviderType,
)
from app.connections.domain.repositories.librarian_repository import (
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
    string_config_value,
)
from app.connections.infrastructure.librarians.provider_types import (
    parse_auth_type,
    parse_provider_type,
)
from app.librarian.application.delegate_execution_contracts import (
    LibrarianDelegateExecutor,
    LibrarianExecutionPlan,
)
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
    LibrarianDelegateResult,
)
from app.librarian.domain.event_enum.collaboration_enums import LibrarianDelegateStatus
from app.operations.application.external_api_rate_limit import (
    ExternalApiRateLimiter,
    ExternalApiRateLimitError,
    NoopExternalApiRateLimiter,
)
from asyncer import asyncify
from openai import OpenAIError

_DEFAULT_MODEL = "gpt-5.5"
_LIBRARIAN_SYSTEM_RULE = """
You are Alexandria Librarian, the librarian for heterarchy-alexandria.
Your purpose is to help Hermes and the user find, evaluate, and apply durable
library assets: skills, prompts, Context Vault memories, decisions, handoffs,
research notes, prior usage, and source references.

Operating rules:
- Act as a librarian and evidence guide, not as a generic chat assistant.
- Prefer concise, actionable answers grounded in the prompt and available brief.
- Do not invent library contents, source refs, tool results, or prior decisions.
- If context is missing, say what is missing and recommend the smallest useful
  fetch/search/recall step.
- Never expose secrets, API keys, OAuth tokens, refresh tokens, Authorization
  headers, connection strings, or operator keys.
- Separate answer, evidence/source refs, gaps, and recommended next actions when
  the prompt asks for analysis.
- When the user asks count/list/inventory questions such as "how many skills",
  answer with the total count first, then show only the top 5 representative
  matches by default as a numbered list with title/type/short reason when those
  fields are available.
- Do not dump the full inventory unless the user explicitly asks for the full
  list or a larger limit; explain that the remaining results can be continued or
  expanded in natural product language.
- Do not create, update, compact, or persist durable Memory Compact artifacts.
  Memory lifecycle and compaction belong to Memory Steward; when such work is
  requested, return evidence and a concise handoff for Memory Steward instead.
- Do not expose raw API routes, backend endpoints, UI paths, headers, or
  implementation-only identifiers in ordinary user answers unless the user
  explicitly asks for API/endpoint details.
- Do not answer inventory questions with only a vague relevance summary; include
  the concrete visible list used for the count, or state that a fetch/search step
  is required before the count can be trusted.
""".strip()
_DEFAULT_INSTRUCTIONS = "Return concise implementation guidance."
logger = logging.getLogger(__name__)
_SUMMARY_FETCHER = OpenAIResponseSummaryFetcher(strip_text_response=True)


class OpenAIProviderDelegateExecutor(LibrarianDelegateExecutor):
    """Execute librarian delegate prompts through OpenAI-style providers."""

    def __init__(
        self,
        secret_repo: IProviderSecretRepository,
        openai_client_builder: OpenAIClientBuilder = build_openai_client,
        rate_limiter: ExternalApiRateLimiter | None = None,
    ) -> None:
        """Initialize the provider-backed executor.

        Args:
            secret_repo: Provider secret resolver boundary.
            openai_client_builder: SDK client constructor boundary.
        """
        self.secret_repo = secret_repo
        self._codex_config_builder = OpenAICodexClientConfigBuilder(secret_repo)
        self.openai_client_builder = openai_client_builder
        self._rate_limiter = rate_limiter or NoopExternalApiRateLimiter()

    async def execute(
        self,
        *,
        command: HermesLibrarianAskCommand,
        plan: LibrarianExecutionPlan,
        fallback: LibrarianDelegateResult,
    ) -> LibrarianDelegateResult:
        """Execute one delegate plan with an OpenAI-compatible Responses API.

        Args:
            command: Ask-librarian command carrying the prompt.
            plan: Resolved provider/profile execution plan.
            fallback: Safe deterministic result used when execution is unavailable.

        Returns:
            LibrarianDelegateResult: Provider-backed result or safe fallback.
        """
        if plan.provider is None:
            return fallback
        provider_type = parse_provider_type(plan.provider.provider_type)
        auth_type = parse_auth_type(plan.provider.auth_type)
        client_config = await self._client_config(
            provider_id=plan.provider.id,
            provider_type=provider_type,
            auth_type=auth_type,
        )
        if client_config is None:
            return _skipped_result(fallback, "Provider credentials unavailable")

        client = self.openai_client_builder(client_config)
        model = _model_for_plan(plan)
        instructions = _instructions_for_plan(plan)
        prompt = _delegate_prompt(command)
        try:
            await self._rate_limiter.acquire(
                _provider_scope(provider_type),
                f"librarian-delegate:{plan.provider.id}",
            )
            if provider_type is ProviderType.OPENAI_CODEX:
                summary = await asyncify(
                    _SUMMARY_FETCHER.fetch_codex_stream_summary,
                    abandon_on_cancel=True,
                )(
                    client,
                    model,
                    prompt,
                    instructions,
                )
            else:
                summary = await asyncify(
                    _SUMMARY_FETCHER.fetch_openai_summary,
                    abandon_on_cancel=True,
                )(
                    client,
                    model,
                    prompt,
                    instructions,
                )
        except (ExternalApiRateLimitError, OpenAIError) as error:
            _log_provider_execution_failure(
                provider_id=plan.provider.id,
                provider_type=provider_type,
                error=error,
            )
            return _skipped_result(fallback, "Provider execution failed")
        if not summary:
            return _skipped_result(fallback, "Provider returned an empty response")
        return replace(
            fallback,
            status=LibrarianDelegateStatus.COMPLETED,
            summary=summary,
        )

    async def _client_config(
        self,
        *,
        provider_id: str,
        provider_type: ProviderType | None,
        auth_type: AuthType,
    ) -> OpenAIClientConfig | None:
        if provider_type is ProviderType.OPENAI and auth_type is AuthType.API_KEY:
            api_key = await self.secret_repo.resolve(
                provider_id,
                ProviderSecretKey.API_KEY.value,
            )
            if not api_key:
                return None
            return OpenAIClientConfig(api_key=api_key)
        if provider_type is ProviderType.OPENAI_CODEX and auth_type is AuthType.OAUTH:
            return await self._codex_client_config(provider_id)
        return None

    async def _codex_client_config(self, provider_id: str) -> OpenAIClientConfig | None:
        client_config = await self._codex_config_builder.build(provider_id=provider_id)
        return client_config


def _delegate_prompt(command: HermesLibrarianAskCommand) -> str:
    packet = command.librarian_brief
    prompt = command.prompt if packet is None or not packet.strip() else packet.strip()
    if command.task_summary is None or not command.task_summary.strip():
        return prompt
    return "\n\n".join(
        [
            "# Hermes Task Summary",
            command.task_summary.strip(),
            "# Librarian Request Packet",
            prompt,
        ]
    )


def _provider_scope(provider_type: ProviderType | None) -> str:
    if provider_type is None:
        return "openai-compatible"
    return provider_type.value


def _log_provider_execution_failure(
    *,
    provider_id: str,
    provider_type: ProviderType | None,
    error: Exception,
) -> None:
    logger.warning(
        "Librarian delegate provider execution failed",
        extra={
            "provider_id": provider_id,
            "provider_type": None if provider_type is None else provider_type.value,
            "error_type": type(error).__name__,
        },
    )


def _instructions_for_plan(plan: LibrarianExecutionPlan) -> str:
    role_prompt = string_config_value(plan.resolution.librarian_role_prompt)
    if role_prompt is None:
        role_prompt = _DEFAULT_INSTRUCTIONS
    return f"{_LIBRARIAN_SYSTEM_RULE}\n\nTask-specific librarian role guidance:\n{role_prompt}"


def _model_for_plan(plan: LibrarianExecutionPlan) -> str:
    if plan.resolution.librarian_model is not None:
        return plan.resolution.librarian_model
    if plan.provider is None:
        return _DEFAULT_MODEL
    model = string_config_value(plan.provider.config.get("model"))
    if model is None:
        return _DEFAULT_MODEL
    return model


def _skipped_result(
    fallback: LibrarianDelegateResult,
    summary: str,
) -> LibrarianDelegateResult:
    return replace(
        fallback,
        status=LibrarianDelegateStatus.SKIPPED,
        summary=summary,
    )
