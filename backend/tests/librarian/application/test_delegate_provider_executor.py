"""Provider-backed librarian delegate executor tests."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio

from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import AuthType, ProviderType
from app.librarian.application.delegation.delegate_execution_contracts import (
    LibrarianDelegateExecutor,
    LibrarianExecutionPlan,
    LibrarianProfileResolution,
)
from app.librarian.application.delegation.delegate_execution_runner import (
    execute_delegates,
)
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
    LibrarianDelegateResult,
)
from app.librarian.domain.event_enum.collaboration_enums import (
    LibrarianDelegateKind,
    LibrarianDelegateStatus,
)


class RecordingDelegateExecutor(LibrarianDelegateExecutor):
    """Fake executor that records provider-backed execution requests."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.provider_ids: list[str] = []

    async def execute(
        self,
        *,
        command: HermesLibrarianAskCommand,
        plan: LibrarianExecutionPlan,
        fallback: LibrarianDelegateResult,
    ) -> LibrarianDelegateResult:
        self.prompts.append(command.prompt)
        if plan.provider is not None:
            self.provider_ids.append(plan.provider.id)
        return LibrarianDelegateResult(
            profile_id=fallback.profile_id,
            provider_id=fallback.provider_id,
            status=LibrarianDelegateStatus.COMPLETED,
            delegate_type=LibrarianDelegateKind.LIBRARY_SEARCH,
            summary=f"provider answered: {command.prompt}",
            matched_specialties=fallback.matched_specialties,
        )


def test_execute_delegates_uses_injected_provider_executor() -> None:
    async def scenario() -> None:
        executor = RecordingDelegateExecutor()
        command = _command("Need OpenAI OAuth executor evidence")
        provider = _provider("openai-main", ProviderType.OPENAI, AuthType.API_KEY)
        plan = LibrarianExecutionPlan(
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

        delegates = await execute_delegates(
            [plan],
            max_librarian_agents=1,
            command=command,
            executor=executor,
        )

        assert executor.prompts == ["Need OpenAI OAuth executor evidence"]
        assert executor.provider_ids == ["openai-main"]
        assert delegates[0].summary == (
            "provider answered: Need OpenAI OAuth executor evidence"
        )
        assert delegates[0].matched_specialties == ("oauth",)

    anyio.run(scenario)


def _command(prompt: str) -> HermesLibrarianAskCommand:
    return HermesLibrarianAskCommand(
        prompt=prompt,
        agent_name="Hermes",
        project="heterarchy-alexandria",
        task_summary=None,
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
) -> LibrarianProvider:
    return LibrarianProvider(
        id=provider_id,
        name=provider_id,
        provider_type=provider_type,
        auth_type=auth_type,
        enabled=True,
        config={},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
