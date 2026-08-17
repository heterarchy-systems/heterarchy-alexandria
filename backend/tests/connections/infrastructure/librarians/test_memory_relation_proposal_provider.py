"""Secure runtime provider tests for memory relation proposals."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import anyio
from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import AuthType, ProviderType
from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.connections.infrastructure.librarians.memory_relation_proposal_provider import (
    ConfiguredMemoryRelationProposalProvider,
)
from app.connections.infrastructure.librarians.openai_adapter import OpenAIClientConfig
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemoryRecallCandidate,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import MemoryRelationType
from openai import OpenAI

NOW = datetime(2026, 7, 25, tzinfo=UTC)
SECRET = "secret-api-key-that-must-not-enter-the-prompt"


class _ProviderRepo:
    def __init__(self, provider: LibrarianProvider | None) -> None:
        self.provider = provider
        self.calls: list[str] = []

    async def get(self, provider_id: str) -> LibrarianProvider | None:
        self.calls.append(provider_id)
        return self.provider


class _SecretRepo:
    def __init__(self, values: dict[tuple[str, str], str]) -> None:
        self.values = values
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, provider_id: str, key_name: str) -> str | None:
        self.calls.append((provider_id, key_name))
        return self.values.get((provider_id, key_name))


def _provider(*, enabled: bool = True) -> LibrarianProvider:
    return LibrarianProvider(
        id="openai-memory",
        name="Memory relation provider",
        provider_type=ProviderType.OPENAI,
        auth_type=AuthType.API_KEY,
        enabled=enabled,
        config={"model": "provider-model"},
        created_at=NOW,
        updated_at=NOW,
    )


def _candidate() -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id="candidate-1",
        title="Candidate",
        body="New durable memory state",
        canonical_claims=(),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        tags=(),
        source_refs=(),
        recorded_at=NOW,
        observed_at=None,
        valid_from=None,
        valid_to=None,
        requested_lifecycle="active",
        content_hash="candidate-hash",
    )


def _existing() -> MemoryRecallCandidate:
    return MemoryRecallCandidate(
        context_id="obsidian:existing-1",
        title="Existing",
        body="Existing durable memory state",
        canonical_claims=(),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        source_identity=None,
        content_hash="existing-hash",
        recorded_at=NOW,
        observed_at=None,
        valid_from=None,
        valid_to=None,
        source_refs=(),
    )


def test_unconfigured_provider_skips_repository_and_secret_access() -> None:
    provider_repo = _ProviderRepo(_provider())
    secret_repo = _SecretRepo({("openai-memory", "api_key"): SECRET})
    configured = ConfiguredMemoryRelationProposalProvider(
        provider_repo=cast(ILibrarianProviderRepository, provider_repo),
        secret_repo=cast(IProviderSecretRepository, secret_repo),
        provider_id="  ",
        default_model="gpt-default",
        timeout_seconds=30.0,
    )

    proposal = anyio.run(configured.propose, _candidate(), _existing())

    assert proposal is None
    assert provider_repo.calls == []
    assert secret_repo.calls == []


def test_disabled_or_missing_secret_provider_fails_closed() -> None:
    disabled_repo = _ProviderRepo(_provider(enabled=False))
    disabled_secret_repo = _SecretRepo({("openai-memory", "api_key"): SECRET})
    disabled = ConfiguredMemoryRelationProposalProvider(
        provider_repo=cast(ILibrarianProviderRepository, disabled_repo),
        secret_repo=cast(IProviderSecretRepository, disabled_secret_repo),
        provider_id="openai-memory",
        default_model="gpt-default",
        timeout_seconds=30.0,
    )
    missing_repo = _ProviderRepo(_provider())
    missing_secret_repo = _SecretRepo({})
    missing = ConfiguredMemoryRelationProposalProvider(
        provider_repo=cast(ILibrarianProviderRepository, missing_repo),
        secret_repo=cast(IProviderSecretRepository, missing_secret_repo),
        provider_id="openai-memory",
        default_model="gpt-default",
        timeout_seconds=30.0,
    )

    disabled_result = anyio.run(disabled.propose, _candidate(), _existing())
    missing_result = anyio.run(missing.propose, _candidate(), _existing())

    assert disabled_result is None
    assert disabled_secret_repo.calls == []
    assert missing_result is None
    assert missing_secret_repo.calls == [("openai-memory", "api_key")]


def test_enabled_api_key_provider_uses_encrypted_secret_and_provider_model() -> None:
    provider_repo = _ProviderRepo(_provider())
    secret_repo = _SecretRepo({("openai-memory", "api_key"): SECRET})
    client_configs: list[OpenAIClientConfig] = []
    executions: list[tuple[str, str, str]] = []

    def client_builder(config: OpenAIClientConfig) -> OpenAI:
        client_configs.append(config)
        return cast(OpenAI, object())

    def response_fetcher(
        client: OpenAI,
        model: str,
        prompt: str,
        instructions: str,
    ) -> str:
        _ = client
        executions.append((model, prompt, instructions))
        return (
            '{"relation":"DUPLICATE","confidence":0.9,'
            '"reason":"Equivalent durable memory"}'
        )

    configured = ConfiguredMemoryRelationProposalProvider(
        provider_repo=cast(ILibrarianProviderRepository, provider_repo),
        secret_repo=cast(IProviderSecretRepository, secret_repo),
        provider_id=" openai-memory ",
        default_model="gpt-default",
        timeout_seconds=12.5,
        openai_client_builder=client_builder,
        response_fetcher=response_fetcher,
    )

    proposal = anyio.run(configured.propose, _candidate(), _existing())

    assert proposal is not None
    assert proposal.relation is MemoryRelationType.DUPLICATE
    assert provider_repo.calls == ["openai-memory"]
    assert secret_repo.calls == [("openai-memory", "api_key")]
    assert len(client_configs) == 1
    assert client_configs[0].api_key == SECRET
    assert client_configs[0].timeout == 12.5
    assert executions[0][0] == "provider-model"
    assert SECRET not in executions[0][1]
    assert SECRET not in executions[0][2]
