"""Hermes-facing collaboration service for librarian fallback decisions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.librarian.application.delegation.delegate_execution_contracts import (
    LibrarianDelegateExecutor,
)
from app.librarian.application.delegation.delegate_execution_planning import (
    build_execution_plans,
    execution_profile_id,
    execution_provider_id,
    first_plan,
    representative_resolution,
)
from app.librarian.application.delegation.delegate_route_preview import (
    build_route_preview,
)
from app.librarian.application.delegation.hermes_collaboration_delegate_policy import (
    completed_delegate_count,
    delegate_decision,
)
from app.librarian.application.delegation.hermes_collaboration_identity import (
    collaboration_job_id,
)
from app.librarian.application.delegation.hermes_collaboration_payload_mapper import (
    ask_payload,
)
from app.librarian.application.delegation.hermes_collaboration_provider_selector import (
    HermesCollaborationProviderSelector,
)
from app.librarian.application.routing.profile_routing import LibrarianProfileRouter
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
    HermesLibrarianAskResult,
)
from app.librarian.domain.repositories.agent_repository import IAgentRepository
from app.librarian.domain.types.hermes_collaboration_payload_types import (
    HermesLibrarianAskPayload,
)
from app.shared.types.types_convert_utils import now_utc


class HermesCollaborationService:
    """Coordinate routing while focused collaborators own execution policies."""

    def __init__(
        self,
        provider_repo: ILibrarianProviderRepository,
        agent_repo: IAgentRepository,
        secret_repo: IProviderSecretRepository,
        now_provider: Callable[[], datetime] = now_utc,
        delegate_executor: LibrarianDelegateExecutor | None = None,
    ) -> None:
        """Initialize collaboration orchestration dependencies.

        Args:
            provider_repo: Librarian provider repository.
            agent_repo: Agent profile repository.
            secret_repo: Provider secret repository used for execution readiness.
            now_provider: Clock boundary for deterministic job ids.
            delegate_executor: Optional provider-backed delegate executor.
        """
        self._now_provider = now_provider
        self._delegate_executor = delegate_executor
        self._profile_router = LibrarianProfileRouter(agent_repo)
        self._provider_selector = HermesCollaborationProviderSelector(
            provider_repository=provider_repo,
            credential_repository=secret_repo,
            now_provider=now_provider,
        )

    async def ask_librarian(
        self,
        command: HermesLibrarianAskCommand,
    ) -> HermesLibrarianAskPayload:
        """Return collaboration guidance or a profile-backed delegation result.

        Args:
            command: Ask-librarian command from API or MCP.

        Returns:
            Public collaboration result.
        """
        routing = await self._profile_router.route(command)
        executable_providers = await self._provider_selector.list_execution_ready()
        plans = build_execution_plans(command, routing, executable_providers)
        executable_plans = [plan for plan in plans if plan.provider is not None]
        representative_plan = (
            executable_plans[0] if executable_plans else first_plan(plans)
        )
        top_level_resolution = representative_resolution(
            command,
            routing,
            representative_plan,
        )
        should_delegate = command.delegate_to_librarian and bool(executable_plans)
        now = self._now_provider()
        job_id = collaboration_job_id(
            command=command,
            resolution=top_level_resolution,
            routing=routing,
            delegated=should_delegate,
            now=now,
        )
        delegates, status, decision, recommendation = await delegate_decision(
            should_delegate,
            executable_plans,
            routing.max_librarian_agents,
            command=command,
            executor=self._delegate_executor,
        )
        route_preview = build_route_preview(
            representative_plan=representative_plan,
            routing=routing,
            delegated=should_delegate,
            executable_count=completed_delegate_count(delegates),
        )
        result = HermesLibrarianAskResult(
            job_id=job_id,
            status=status,
            decision=decision,
            librarian_available=bool(executable_plans),
            self_acquisition_allowed=True,
            recommendation=recommendation,
            provider_id=execution_provider_id(representative_plan),
            candidate_id=None,
            librarian_profile_id=execution_profile_id(representative_plan),
            librarian_model=top_level_resolution.librarian_model,
            librarian_role_prompt=top_level_resolution.librarian_role_prompt,
            max_librarian_agents=top_level_resolution.max_librarian_agents,
            route_preview=tuple(route_preview),
            selected_profiles=tuple(
                profile.id for profile in routing.selected_profiles
            ),
            matched_specialties=tuple(routing.matched_specialties),
            quality_review_added=routing.quality_review_added,
            routing_reason=routing.reason,
            delegates=tuple(delegates),
        )
        return ask_payload(result)
