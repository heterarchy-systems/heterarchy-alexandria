"""OpenAI/Codex provider-backed librarian delegate executor tests."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import cast

import anyio
import pytest
from app.connections.domain.entities.read_models import LibrarianProvider
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
)
from app.connections.infrastructure.librarians.openai_delegate_executor import (
    OpenAIProviderDelegateExecutor,
)
from app.librarian.application.delegate_execution_contracts import (
    LibrarianExecutionPlan,
    LibrarianProfileResolution,
)
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
    LibrarianDelegateResult,
)
from app.librarian.domain.event_enum.collaboration_enums import (
    LibrarianDelegateKind,
    LibrarianDelegateStatus,
)
from app.shared.serialization.orjson_codec import dumps_json
from app.shared.types.extra_types import JSONValue
from openai import OpenAIError
from openai.types.responses import ResponseTextDeltaEvent


class FakeSecretRepository:
    """In-memory secret repository for executor tests."""

    def __init__(self, values: dict[tuple[str, str], str]) -> None:
        self.values = values

    async def resolve(self, provider_id: str, key_name: str) -> str | None:
        return self.values.get((provider_id, key_name))

    async def set_secret(self, *, provider_id: str, key_name: str, value: str) -> None:
        self.values[(provider_id, key_name)] = value

    async def delete_for_provider(self, provider_id: str, key_name: str) -> None:
        self.values.pop((provider_id, key_name), None)


class FakeResponse:
    """Minimal SDK response carrying output_text."""

    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class FakeResponsesResource:
    """Minimal SDK responses resource."""

    def __init__(self) -> None:
        self.calls: list[dict[str, JSONValue]] = []

    def create(
        self,
        *,
        model: str,
        input: str | list[dict[str, JSONValue]],
        instructions: str,
        store: bool | None = None,
        stream: bool = False,
    ) -> FakeResponse | list[ResponseTextDeltaEvent]:
        self.calls.append(
            {
                "model": model,
                "input": input,
                "instructions": instructions,
                "store": store,
                "stream": stream,
            }
        )
        if stream:
            return [
                ResponseTextDeltaEvent(
                    content_index=0,
                    delta="Provider-backed ",
                    item_id="item-1",
                    logprobs=[],
                    output_index=0,
                    sequence_number=1,
                    type="response.output_text.delta",
                ),
                ResponseTextDeltaEvent(
                    content_index=0,
                    delta="answer without secrets",
                    item_id="item-1",
                    logprobs=[],
                    output_index=0,
                    sequence_number=2,
                    type="response.output_text.delta",
                ),
            ]
        return FakeResponse("Provider-backed answer without secrets")


class FakeOpenAIClient:
    """Minimal SDK client with responses.create."""

    def __init__(self) -> None:
        self.responses = FakeResponsesResource()


class BlockingResponsesResource(FakeResponsesResource):
    """SDK responses fake that blocks until an async task releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self._release = Event()
        self.released_by_async_task = False

    def create(
        self,
        *,
        model: str,
        input: str | list[dict[str, JSONValue]],
        instructions: str,
        store: bool | None = None,
        stream: bool = False,
    ) -> FakeResponse | list[ResponseTextDeltaEvent]:
        self.calls.append(
            {
                "model": model,
                "input": input,
                "instructions": instructions,
                "store": store,
                "stream": stream,
            }
        )
        self.started.set()
        self.released_by_async_task = self._release.wait(timeout=0.2)
        return FakeResponse("Provider-backed answer after blocking boundary")

    def release(self) -> None:
        """Release the blocked SDK boundary call."""
        self._release.set()


class BlockingOpenAIClient:
    """Minimal SDK client whose responses resource blocks."""

    def __init__(self) -> None:
        self.responses = BlockingResponsesResource()


class FailingResponsesResource:
    """SDK responses resource that fails at the provider boundary."""

    def create(
        self,
        *,
        model: str,
        input: str | list[dict[str, JSONValue]],
        instructions: str,
        store: bool | None = None,
        stream: bool = False,
    ) -> FakeResponse | list[ResponseTextDeltaEvent]:
        raise OpenAIError("provider unavailable")


class FailingOpenAIClient:
    """Minimal SDK client whose provider call fails."""

    def __init__(self) -> None:
        self.responses = FailingResponsesResource()


class ContractBugResponsesResource:
    """SDK responses resource that simulates an unexpected local bug."""

    def create(
        self,
        *,
        model: str,
        input: str | list[dict[str, JSONValue]],
        instructions: str,
        store: bool | None = None,
        stream: bool = False,
    ) -> FakeResponse | list[ResponseTextDeltaEvent]:
        raise ValueError("local contract bug")


class ContractBugOpenAIClient:
    """Minimal SDK client whose response adapter has a local bug."""

    def __init__(self) -> None:
        self.responses = ContractBugResponsesResource()


def test_openai_api_key_executor_sends_prompt_to_responses_api() -> None:
    async def scenario() -> None:
        configs: list[OpenAIClientConfig] = []
        client = FakeOpenAIClient()

        def build_client(config: OpenAIClientConfig):
            configs.append(config)
            return client

        secret_repo = FakeSecretRepository(
            {
                ("openai-main", ProviderSecretKey.API_KEY.value): "sk-secret-value",
            }
        )
        executor = OpenAIProviderDelegateExecutor(
            secret_repo=cast(IProviderSecretRepository, secret_repo),
            openai_client_builder=cast(OpenAIClientBuilder, build_client),
        )
        result = await executor.execute(
            command=_command("Summarize OAuth executor risk"),
            plan=_plan(_provider("openai-main", ProviderType.OPENAI, AuthType.API_KEY)),
            fallback=_fallback("openai-main"),
        )

        assert configs == [
            OpenAIClientConfig(api_key="sk-secret-value"),
        ]
        assert len(client.responses.calls) == 1
        call = client.responses.calls[0]
        assert call["model"] == "gpt-5.5"
        assert call["input"] == "Summarize OAuth executor risk"
        assert call["store"] is None
        assert call["stream"] is False
        assert "Alexandria Librarian" in str(call["instructions"])
        assert "Return concise implementation guidance." in str(call["instructions"])
        assert result.summary == "Provider-backed answer without secrets"
        assert "sk-secret-value" not in repr(result)

    anyio.run(scenario)


def test_openai_api_key_executor_offloads_blocking_sdk_call_from_event_loop() -> None:
    async def scenario() -> None:
        client = BlockingOpenAIClient()

        def build_client(config: OpenAIClientConfig):
            return client

        secret_repo = FakeSecretRepository(
            {
                ("openai-main", ProviderSecretKey.API_KEY.value): "sk-secret-value",
            }
        )
        executor = OpenAIProviderDelegateExecutor(
            secret_repo=cast(IProviderSecretRepository, secret_repo),
            openai_client_builder=cast(OpenAIClientBuilder, build_client),
        )
        results: list[LibrarianDelegateResult] = []

        async def execute_delegate() -> None:
            result = await executor.execute(
                command=_command("Summarize blocking provider risk"),
                plan=_plan(
                    _provider("openai-main", ProviderType.OPENAI, AuthType.API_KEY)
                ),
                fallback=_fallback("openai-main"),
            )
            results.append(result)

        async def release_when_sdk_call_starts() -> None:
            while not client.responses.started.is_set():
                await anyio.sleep(0)
            client.responses.release()

        with anyio.fail_after(1):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(execute_delegate)
                task_group.start_soon(release_when_sdk_call_starts)

        assert client.responses.released_by_async_task is True
        assert [result.summary for result in results] == [
            "Provider-backed answer after blocking boundary"
        ]

    anyio.run(scenario)


def test_openai_api_key_executor_includes_task_summary_in_provider_prompt() -> None:
    """Provider delegates should receive searched inventory context, not just refs."""

    async def scenario() -> None:
        client = FakeOpenAIClient()

        def build_client(config: OpenAIClientConfig):
            return client

        secret_repo = FakeSecretRepository(
            {
                ("openai-main", ProviderSecretKey.API_KEY.value): "sk-secret-value",
            }
        )
        executor = OpenAIProviderDelegateExecutor(
            secret_repo=cast(IProviderSecretRepository, secret_repo),
            openai_client_builder=cast(OpenAIClientBuilder, build_client),
        )
        await executor.execute(
            command=_command(
                "hermes와 관련된 skill은 몇개정도 있지?",
                task_summary=(
                    "Direct search inventory total count: 42.\n"
                    "Visible top 5 representative items for count/list/inventory answers."
                ),
            ),
            plan=_plan(_provider("openai-main", ProviderType.OPENAI, AuthType.API_KEY)),
            fallback=_fallback("openai-main"),
        )

        provider_prompt = str(client.responses.calls[0]["input"])
        assert "Direct search inventory total count: 42." in provider_prompt
        assert "Visible top 5 representative items" in provider_prompt
        assert "hermes와 관련된 skill은 몇개정도 있지?" in provider_prompt

    anyio.run(scenario)


def test_librarian_instructions_require_counts_and_lists_for_inventory_questions() -> (
    None
):
    """Librarian guidance should answer count/list prompts with structured inventory."""

    async def scenario() -> None:
        client = FakeOpenAIClient()

        def build_client(config: OpenAIClientConfig):
            return client

        secret_repo = FakeSecretRepository(
            {
                ("openai-main", ProviderSecretKey.API_KEY.value): "***",
            }
        )
        executor = OpenAIProviderDelegateExecutor(
            secret_repo=cast(IProviderSecretRepository, secret_repo),
            openai_client_builder=cast(OpenAIClientBuilder, build_client),
        )
        await executor.execute(
            command=_command("hermes 와 관련된 skills 이 몇개지?"),
            plan=_plan(_provider("openai-main", ProviderType.OPENAI, AuthType.API_KEY)),
            fallback=_fallback("openai-main"),
        )

        instructions = str(client.responses.calls[0]["instructions"])
        assert "count" in instructions
        assert "top 5" in instructions
        assert "numbered list" in instructions
        assert "Do not expose raw API routes" in instructions
        assert "UI paths" in instructions
        assert "natural product language" in instructions

    anyio.run(scenario)


def test_openai_codex_executor_uses_oauth_token_and_codex_base_url() -> None:
    async def scenario() -> None:
        configs: list[OpenAIClientConfig] = []
        client = FakeOpenAIClient()

        def build_client(config: OpenAIClientConfig):
            configs.append(config)
            return client

        secret_repo = FakeSecretRepository(
            {
                (
                    "codex-main",
                    ProviderSecretKey.OAUTH_ACCESS_TOKEN.value,
                ): _fake_oauth_jwt(account_id="acct-test-123"),
                (
                    "codex-main",
                    ProviderSecretKey.OAUTH_EXPIRES_AT.value,
                ): (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        )
        executor = OpenAIProviderDelegateExecutor(
            secret_repo=cast(IProviderSecretRepository, secret_repo),
            openai_client_builder=cast(OpenAIClientBuilder, build_client),
        )
        result = await executor.execute(
            command=_command("Use Codex OAuth"),
            plan=_plan(
                _provider(
                    "codex-main",
                    ProviderType.OPENAI_CODEX,
                    AuthType.OAUTH,
                    model="gpt-5.5",
                )
            ),
            fallback=_fallback("codex-main"),
        )

        assert len(configs) == 1
        assert configs[0].api_key == _fake_oauth_jwt(account_id="acct-test-123")
        assert configs[0].base_url == "https://chatgpt.com/backend-api/codex"
        assert configs[0].default_headers == {
            "User-Agent": "codex_cli_rs/0.0.0 (heterarchy-alexandria)",
            "originator": "codex_cli_rs",
            "ChatGPT-Account-ID": "acct-test-123",
        }
        assert result.summary == "Provider-backed answer without secrets"
        assert len(client.responses.calls) == 1
        call = client.responses.calls[0]
        assert call["model"] == "gpt-5.5"
        assert call["input"] == [{"role": "user", "content": "Use Codex OAuth"}]
        assert call["store"] is False
        assert call["stream"] is True
        assert "Alexandria Librarian" in str(call["instructions"])
        assert "Return concise implementation guidance." in str(call["instructions"])
        assert "acct-test-123" not in repr(result)

    anyio.run(scenario)


def test_openai_executor_returns_skipped_when_credentials_are_unavailable() -> None:
    async def scenario() -> None:
        executor = OpenAIProviderDelegateExecutor(
            secret_repo=cast(IProviderSecretRepository, FakeSecretRepository({})),
        )
        result = await executor.execute(
            command=_command("Summarize missing credentials"),
            plan=_plan(_provider("openai-main", ProviderType.OPENAI, AuthType.API_KEY)),
            fallback=_fallback("openai-main"),
        )

        assert result.status is LibrarianDelegateStatus.SKIPPED
        assert result.summary == "Provider credentials unavailable"
        assert result.provider_id == "openai-main"

    anyio.run(scenario)


def test_openai_executor_returns_skipped_when_provider_execution_fails() -> None:
    async def scenario() -> None:
        def build_client(config: OpenAIClientConfig):
            return FailingOpenAIClient()

        secret_repo = FakeSecretRepository(
            {
                ("openai-main", ProviderSecretKey.API_KEY.value): "sk-secret-value",
            }
        )
        executor = OpenAIProviderDelegateExecutor(
            secret_repo=cast(IProviderSecretRepository, secret_repo),
            openai_client_builder=cast(OpenAIClientBuilder, build_client),
        )
        result = await executor.execute(
            command=_command("Summarize provider failure"),
            plan=_plan(_provider("openai-main", ProviderType.OPENAI, AuthType.API_KEY)),
            fallback=_fallback("openai-main"),
        )

        assert result.status is LibrarianDelegateStatus.SKIPPED
        assert result.summary == "Provider execution failed"
        assert "sk-secret-value" not in repr(result)

    anyio.run(scenario)


def test_openai_executor_propagates_unexpected_local_contract_errors() -> None:
    async def scenario() -> None:
        def build_client(config: OpenAIClientConfig):
            return ContractBugOpenAIClient()

        secret_repo = FakeSecretRepository(
            {
                ("openai-main", ProviderSecretKey.API_KEY.value): "sk-secret-value",
            }
        )
        executor = OpenAIProviderDelegateExecutor(
            secret_repo=cast(IProviderSecretRepository, secret_repo),
            openai_client_builder=cast(OpenAIClientBuilder, build_client),
        )

        with pytest.raises(ValueError, match="local contract bug"):
            await executor.execute(
                command=_command("Summarize provider failure"),
                plan=_plan(
                    _provider("openai-main", ProviderType.OPENAI, AuthType.API_KEY)
                ),
                fallback=_fallback("openai-main"),
            )

    anyio.run(scenario)


def _fake_oauth_jwt(*, account_id: str) -> str:
    header = _base64_url_json({"alg": "none"})
    payload = _base64_url_json(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": account_id,
            },
        }
    )
    return f"{header}.{payload}.signature"


def _base64_url_json(value: dict[str, str | dict[str, str]]) -> str:
    raw = dumps_json(value)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _command(
    prompt: str,
    *,
    task_summary: str | None = None,
) -> HermesLibrarianAskCommand:
    return HermesLibrarianAskCommand(
        prompt=prompt,
        agent_name="Hermes",
        project="heterarchy-alexandria",
        task_summary=task_summary,
        delegate_to_librarian=True,
        provider_id=None,
        librarian_profile_id=None,
        librarian_model=None,
        librarian_role_prompt=None,
        max_librarian_agents=1,
        routing_specialties=[],
    )


def _provider(
    provider_id: str,
    provider_type: ProviderType,
    auth_type: AuthType,
    *,
    model: str | None = None,
) -> LibrarianProvider:
    config: dict[str, JSONValue] = {"model": model} if model is not None else {}
    return LibrarianProvider(
        id=provider_id,
        name=provider_id,
        provider_type=provider_type,
        auth_type=auth_type,
        enabled=True,
        config=config,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _plan(provider: LibrarianProvider) -> LibrarianExecutionPlan:
    return LibrarianExecutionPlan(
        profile=None,
        provider=provider,
        resolution=LibrarianProfileResolution(
            provider_id=provider.id,
            librarian_profile_id=None,
            librarian_model="gpt-5.5",
            librarian_role_prompt="Return concise implementation guidance.",
            max_librarian_agents=1,
        ),
        matched_specialties=("oauth",),
    )


def _fallback(provider_id: str) -> LibrarianDelegateResult:
    return LibrarianDelegateResult(
        profile_id="request-default",
        provider_id=provider_id,
        status=LibrarianDelegateStatus.COMPLETED,
        delegate_type=LibrarianDelegateKind.LIBRARY_SEARCH,
        summary="Fallback summary",
        matched_specialties=["oauth"],
    )
