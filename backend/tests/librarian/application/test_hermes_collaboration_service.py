"""Hermes collaboration service tests for Obsidian plugin delegation."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio
import pytest
from app.connections.domain.contracts.librarian_provider_contracts import (
    LibrarianProviderCreate,
    LibrarianProviderUpdate,
)
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
from app.librarian.application.delegate_execution_contracts import (
    LibrarianDelegateExecutor,
    LibrarianExecutionPlan,
)
from app.librarian.application.hermes_collaboration_service import (
    HermesCollaborationService,
)
from app.librarian.domain.contracts.agent_contracts import AgentCreate, AgentUpdate
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
    LibrarianDelegateResult,
)
from app.librarian.domain.entities.read_models import AgentProfile
from app.librarian.domain.entities.source_ref import SourceRef
from app.librarian.domain.event_enum.collaboration_enums import (
    LibrarianDelegateStatus,
)
from app.librarian.domain.repositories.agent_repository import IAgentRepository
from app.shared.exceptions.librarian_exceptions import LibrarianResourceNotFoundError
from app.shared.types.extra_types import JSONObject

FIXED_NOW = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)


class CollaborationProviderRepository(ILibrarianProviderRepository):
    """In-memory provider repository for collaboration route tests."""

    def __init__(self, providers: list[LibrarianProvider]) -> None:
        """Store provider rows returned by list/get operations."""
        self.providers = providers

    async def create(self, payload: LibrarianProviderCreate) -> LibrarianProvider:
        """Create is unused by collaboration route tests."""
        raise NotImplementedError

    async def get(self, provider_id: str) -> LibrarianProvider | None:
        """Return one provider by id."""
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        return None

    async def list_all(self) -> list[LibrarianProvider]:
        """Return all stored providers."""
        return self.providers

    async def update(
        self, provider_id: str, payload: LibrarianProviderUpdate
    ) -> LibrarianProvider:
        """Update is unused by collaboration route tests."""
        raise NotImplementedError

    async def delete(self, provider_id: str) -> None:
        """Delete is unused by collaboration route tests."""
        raise NotImplementedError


class CollaborationAgentRepository(IAgentRepository):
    """In-memory agent profile repository for collaboration route tests."""

    def __init__(self, profiles: list[AgentProfile]) -> None:
        """Store profile rows returned by get operations."""
        self.profiles = profiles

    async def create(self, payload: AgentCreate) -> AgentProfile:
        """Create is unused by collaboration route tests."""
        raise NotImplementedError

    async def get(self, agent_id: str) -> AgentProfile | None:
        """Return one agent profile by id."""
        for profile in self.profiles:
            if profile.id == agent_id:
                return profile
        return None

    async def list_all(self) -> list[AgentProfile]:
        """Return all stored agent profiles."""
        return self.profiles

    async def update(self, agent_id: str, payload: AgentUpdate) -> AgentProfile:
        """Update is unused by collaboration route tests."""
        raise NotImplementedError

    async def delete(self, agent_id: str) -> None:
        """Delete is unused by collaboration route tests."""
        raise NotImplementedError


class CollaborationSecretRepository(IProviderSecretRepository):
    """In-memory provider secret repository for collaboration route tests."""

    def __init__(self, secrets: dict[tuple[str, str], str] | None = None) -> None:
        """Store provider secrets by provider id and key name."""
        self.secrets = {} if secrets is None else secrets

    async def resolve(self, provider_id: str, key_name: str) -> str | None:
        """Return one stored secret value."""
        return self.secrets.get((provider_id, key_name))

    async def set_secret(self, *, provider_id: str, key_name: str, value: str) -> None:
        """Set secret is unused by collaboration route tests."""
        raise NotImplementedError

    async def delete_for_provider(self, provider_id: str, key_name: str) -> None:
        """Delete secret is unused by collaboration route tests."""
        raise NotImplementedError


class SkippingDelegateExecutor(LibrarianDelegateExecutor):
    """Fake executor that simulates provider execution failure."""

    async def execute(
        self,
        *,
        command: HermesLibrarianAskCommand,
        plan: LibrarianExecutionPlan,
        fallback: LibrarianDelegateResult,
    ) -> LibrarianDelegateResult:
        """Return a skipped delegate without raising across the boundary.

        Args:
            command: Ask-librarian command under execution.
            plan: Resolved delegate execution plan.
            fallback: Deterministic delegate metadata.

        Returns:
            LibrarianDelegateResult: Skipped delegate failure evidence.
        """
        return LibrarianDelegateResult(
            profile_id=fallback.profile_id,
            provider_id=fallback.provider_id,
            status=LibrarianDelegateStatus.SKIPPED,
            delegate_type=fallback.delegate_type,
            summary=f"Provider execution failed for: {command.prompt}",
            matched_specialties=fallback.matched_specialties,
        )


def _provider(
    provider_id: str = "00000000-0000-4000-8000-000000000701",
    *,
    enabled: bool = True,
    config: JSONObject | None = None,
) -> LibrarianProvider:
    """Build a provider read model for collaboration route tests."""
    return LibrarianProvider(
        id=provider_id,
        name="codex-oauth",
        provider_type=ProviderType.OPENAI_CODEX.value,
        auth_type=AuthType.OAUTH.value,
        enabled=enabled,
        config={} if config is None else config,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


def _profile(
    profile_id: str = "00000000-0000-4000-8000-000000000601",
    provider_id: str = "00000000-0000-4000-8000-000000000701",
    *,
    role: str = "DEFAULT_SEARCH",
    specialties: list[str] | None = None,
    routing_priority: int = 100,
) -> AgentProfile:
    """Build an agent profile read model for collaboration route tests."""
    return AgentProfile(
        id=profile_id,
        name="Hermes Librarian",
        provider=ProviderType.OPENAI_CODEX.value,
        description="Use project memory first.",
        capabilities=["library-search"],
        preferred_librarian_provider=provider_id,
        preferred_librarian_model="gpt-5.5",
        max_librarian_agents=2,
        librarian_role_prompt="Use project memory before web search.",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        librarian_role=role,
        librarian_specialties=specialties,
        librarian_routing_priority=routing_priority,
    )


def _service(
    providers: list[LibrarianProvider],
    profiles: list[AgentProfile] | None = None,
    secrets: dict[tuple[str, str], str] | None = None,
    delegate_executor: LibrarianDelegateExecutor | None = None,
) -> HermesCollaborationService:
    """Create collaboration service with deterministic clock."""
    return HermesCollaborationService(
        provider_repo=CollaborationProviderRepository(providers),
        agent_repo=CollaborationAgentRepository([] if profiles is None else profiles),
        secret_repo=CollaborationSecretRepository(secrets),
        now_provider=lambda: FIXED_NOW,
        delegate_executor=delegate_executor,
    )


def _oauth_execution_secrets(
    provider_id: str = "00000000-0000-4000-8000-000000000701",
) -> dict[tuple[str, str], str]:
    """Return OAuth secret material that makes a provider executable."""
    return {
        (provider_id, ProviderSecretKey.OAUTH_ACCESS_TOKEN.value): "access-token",
        (
            provider_id,
            ProviderSecretKey.OAUTH_EXPIRES_AT.value,
        ): "2026-05-15T12:10:00+00:00",
    }


def _command(
    prompt: str,
    *,
    delegate: bool = False,
    profile_id: str | None = None,
    provider_id: str | None = None,
    model: str | None = None,
    role_prompt: str | None = None,
    max_agents: int | None = None,
    specialties: tuple[str, ...] = (),
    source_refs: tuple[SourceRef, ...] = (),
) -> HermesLibrarianAskCommand:
    return HermesLibrarianAskCommand(
        prompt=prompt,
        agent_name="Hermes",
        project="heterarchy-alexandria",
        task_summary=None,
        delegate_to_librarian=delegate,
        provider_id=provider_id,
        librarian_profile_id=profile_id,
        librarian_model=model,
        librarian_role_prompt=role_prompt,
        max_librarian_agents=max_agents,
        routing_specialties=specialties,
        source_refs=source_refs,
        librarian_brief=None,
    )


def _run_ask(
    service: HermesCollaborationService,
    command: HermesLibrarianAskCommand,
):
    async def run_case():
        return await service.ask_librarian(command)

    return anyio.run(run_case)


def test_collaboration_suggests_self_research_without_provider() -> None:
    service = _service([])

    payload = _run_ask(service, _command("Need an OAuth callback review skill"))

    assert payload["job_id"].startswith("librarian-job-")
    assert payload["status"] == "GUIDANCE_ONLY"
    assert payload["decision"] == "SUGGEST_HERMES_RESEARCH"
    assert payload["librarian_available"] is False
    assert payload["delegates"] == []


def test_collaboration_delegates_to_explicit_profile_when_provider_is_ready() -> None:
    profile = _profile()
    service = _service([_provider()], [profile], _oauth_execution_secrets())

    payload = _run_ask(
        service,
        _command(
            "Need an MCP usage-recording skill",
            delegate=True,
            profile_id=profile.id,
        ),
    )

    assert payload["status"] == "COMPLETED"
    assert payload["decision"] == "DELEGATE_TO_LIBRARIAN"
    assert payload["librarian_available"] is True
    assert payload["librarian_profile_id"] == profile.id
    assert payload["provider_id"] == "00000000-0000-4000-8000-000000000701"
    assert payload["delegates"][0]["status"] == "COMPLETED"


def test_collaboration_routes_specialty_and_quality_review_profiles() -> None:
    specialist = _profile(
        "00000000-0000-4000-8000-000000000602",
        role="SPECIALIST",
        specialties=["oauth", "fastapi"],
        routing_priority=10,
    )
    reviewer = _profile(
        "00000000-0000-4000-8000-000000000603",
        role="QUALITY_REVIEWER",
        specialties=["security"],
        routing_priority=15,
    )
    default = _profile(
        "00000000-0000-4000-8000-000000000604",
        role="DEFAULT_SEARCH",
        specialties=["library-search"],
        routing_priority=100,
    )
    service = _service(
        [_provider()],
        [default, specialist, reviewer],
        _oauth_execution_secrets(),
    )

    payload = _run_ask(
        service,
        _command("Need an OAuth security review", delegate=True),
    )

    assert payload["selected_profiles"] == [specialist.id, reviewer.id]
    assert payload["matched_specialties"] == ["oauth", "security"]
    assert payload["quality_review_added"] is True
    assert [item["delegate_type"] for item in payload["delegates"]] == [
        "SPECIALTY_REVIEW",
        "QUALITY_REVIEW",
    ]


def test_collaboration_request_overrides_profile_execution_defaults() -> None:
    profile = _profile()
    service = _service([_provider()], [profile], _oauth_execution_secrets())

    payload = _run_ask(
        service,
        _command(
            "Need a deep review",
            delegate=True,
            profile_id=profile.id,
            model="gpt-5.4",
            role_prompt="Perform a narrow security review.",
            max_agents=1,
        ),
    )

    assert payload["librarian_model"] == "gpt-5.4"
    assert payload["librarian_role_prompt"] == "Perform a narrow security review."
    assert payload["max_librarian_agents"] == 1


def test_collaboration_marks_skipped_provider_execution_as_guidance_only() -> None:
    profile = _profile()
    service = _service(
        [_provider()],
        [profile],
        _oauth_execution_secrets(),
        delegate_executor=SkippingDelegateExecutor(),
    )

    payload = _run_ask(
        service,
        _command(
            "Need an MCP usage-recording skill",
            delegate=True,
            profile_id=profile.id,
        ),
    )

    assert payload["status"] == "GUIDANCE_ONLY"
    assert payload["decision"] == "SUGGEST_HERMES_RESEARCH"
    assert payload["delegates"][0]["status"] == "SKIPPED"


def test_collaboration_rejects_unknown_profile() -> None:
    service = _service([_provider()])

    async def run_case() -> None:
        await service.ask_librarian(
            _command("Need a deep review", delegate=True, profile_id="missing-profile")
        )

    with pytest.raises(
        LibrarianResourceNotFoundError,
        match="Librarian profile not found: missing-profile",
    ):
        anyio.run(run_case)
