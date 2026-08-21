"""Deterministic librarian profile routing for Hermes collaboration."""

from __future__ import annotations

from app.librarian.application.routing.profile_routing_contracts import (
    LibrarianRoutingDecision,
    ProfileScore,
)
from app.librarian.application.routing.profile_routing_policy import (
    _DEFAULT_MAX_AUTO_PROFILES,
    _route_scored_profiles,
    matched_specialties_for_profile,
    profile_role,
)
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
)
from app.librarian.domain.entities.read_models import AgentProfile
from app.librarian.domain.event_enum.collaboration_enums import (
    LibrarianProfileRole,
)
from app.librarian.domain.repositories.agent_repository import IAgentRepository
from app.shared.exceptions.librarian_exceptions import LibrarianResourceNotFoundError

__all__ = (
    "LibrarianProfileRouter",
    "LibrarianRoutingDecision",
    "ProfileScore",
    "matched_specialties_for_profile",
    "profile_role",
)


class LibrarianProfileRouter:
    """Select librarian profiles from prompt text and explicit request hints."""

    def __init__(self, agent_repo: IAgentRepository) -> None:
        """Initialize router dependencies.

        Args:
            agent_repo: Agent profile repository.
        """
        self.agent_repo = agent_repo

    async def route(
        self,
        command: HermesLibrarianAskCommand,
    ) -> LibrarianRoutingDecision:
        """Select librarian profiles by explicit id or specialty routing.

        Args:
            command: Ask-librarian command from API/MCP.

        Returns:
            LibrarianRoutingDecision: Selected profiles and routing evidence.
        """
        if command.librarian_profile_id is not None:
            return await self._route_requested_profile(command)

        profiles = [
            profile
            for profile in await self.agent_repo.list_all()
            if profile.librarian_enabled
        ]
        if not profiles:
            return LibrarianRoutingDecision(
                selected_profiles=(),
                matched_specialties=(),
                quality_review_added=False,
                reason="No librarian profiles configured",
                max_librarian_agents=command.max_librarian_agents,
            )

        max_agents = command.max_librarian_agents or _DEFAULT_MAX_AUTO_PROFILES
        return _route_scored_profiles(profiles, command, max_agents)

    async def _route_requested_profile(
        self,
        command: HermesLibrarianAskCommand,
    ) -> LibrarianRoutingDecision:
        profile_ref = command.librarian_profile_id or ""
        profile = await self.agent_repo.get(profile_ref)
        if profile is None:
            profile = await self._profile_by_name(profile_ref)
        if profile is None:
            raise LibrarianResourceNotFoundError(
                f"Librarian profile not found: {command.librarian_profile_id}"
            )
        max_agents = command.max_librarian_agents or profile.max_librarian_agents
        matched = matched_specialties_for_profile(profile, command)
        return LibrarianRoutingDecision(
            selected_profiles=(profile,),
            matched_specialties=matched,
            quality_review_added=profile_role(profile)
            is LibrarianProfileRole.QUALITY_REVIEWER,
            reason=f"Requested librarian profile {profile_ref}",
            max_librarian_agents=max_agents,
        )

    async def _profile_by_name(self, profile_name: str) -> AgentProfile | None:
        profiles = await self.agent_repo.list_all()
        for profile in profiles:
            if profile.name == profile_name:
                return profile
        return None
