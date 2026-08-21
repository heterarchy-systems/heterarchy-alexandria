"""Provider-backed plan resolution for librarian delegates."""

from __future__ import annotations

from app.connections.domain.entities.read_models import LibrarianProvider
from app.librarian.application.delegation.delegate_execution_contracts import (
    LibrarianExecutionPlan,
    LibrarianProfileResolution,
)
from app.librarian.application.routing.profile_routing_contracts import (
    LibrarianRoutingDecision,
)
from app.librarian.application.routing.profile_routing_policy import (
    matched_specialties_for_profile,
)
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
)
from app.librarian.domain.entities.read_models import AgentProfile


def build_execution_plans(
    command: HermesLibrarianAskCommand,
    routing: LibrarianRoutingDecision,
    executable_providers: list[LibrarianProvider],
) -> list[LibrarianExecutionPlan]:
    """Build provider/profile execution plans for a collaboration request.

    Args:
        command: Ask-librarian command from API/MCP.
        routing: Selected librarian profiles and routing metadata.
        executable_providers: Providers that passed execution-readiness checks.

    Returns:
        list[LibrarianExecutionPlan]: Candidate delegate plans.
    """
    provider_by_reference = _provider_reference_lookup(executable_providers)
    plans: list[LibrarianExecutionPlan] = []
    for profile in routing.selected_profiles:
        resolution = _profile_resolution(command, profile, routing.max_librarian_agents)
        provider = _plan_provider(
            resolution.provider_id, provider_by_reference, executable_providers
        )
        plans.append(
            LibrarianExecutionPlan(
                profile=profile,
                provider=provider,
                resolution=resolution,
                matched_specialties=matched_specialties_for_profile(profile, command),
            )
        )
    if plans:
        return plans
    return [_request_default_plan(command, provider_by_reference, executable_providers)]


def first_plan(plans: list[LibrarianExecutionPlan]) -> LibrarianExecutionPlan | None:
    """Return the first execution plan when one exists.

    Args:
        plans: Planned delegate executions.

    Returns:
        LibrarianExecutionPlan | None: First plan, or None.
    """
    if plans:
        return plans[0]
    return None


def representative_resolution(
    command: HermesLibrarianAskCommand,
    routing: LibrarianRoutingDecision,
    representative_plan: LibrarianExecutionPlan | None,
) -> LibrarianProfileResolution:
    """Resolve top-level response execution settings.

    Args:
        command: Ask-librarian command from API/MCP.
        routing: Selected profiles and routing metadata.
        representative_plan: Preferred executable or preview plan.

    Returns:
        LibrarianProfileResolution: Top-level execution settings.
    """
    if representative_plan is not None:
        return representative_plan.resolution
    return LibrarianProfileResolution(
        provider_id=command.provider_id,
        librarian_profile_id=None,
        librarian_model=command.librarian_model,
        librarian_role_prompt=command.librarian_role_prompt,
        max_librarian_agents=routing.max_librarian_agents,
    )


def execution_provider_id(plan: LibrarianExecutionPlan | None) -> str | None:
    """Return the provider id for a representative execution plan.

    Args:
        plan: Representative execution plan.

    Returns:
        str | None: Provider id when available.
    """
    if plan is None or plan.provider is None:
        return None
    return plan.provider.id


def execution_profile_id(plan: LibrarianExecutionPlan | None) -> str | None:
    """Return the profile id for a representative execution plan.

    Args:
        plan: Representative execution plan.

    Returns:
        str | None: Profile id when available.
    """
    if plan is None or plan.profile is None:
        return None
    return plan.profile.id


def _request_default_plan(
    command: HermesLibrarianAskCommand,
    provider_by_reference: dict[str, LibrarianProvider],
    executable_providers: list[LibrarianProvider],
) -> LibrarianExecutionPlan:
    provider = _plan_provider(
        command.provider_id,
        provider_by_reference,
        executable_providers,
    )
    if provider is None and not command.provider_id and executable_providers:
        provider = executable_providers[0]
    resolution = LibrarianProfileResolution(
        provider_id=command.provider_id,
        librarian_profile_id=None,
        librarian_model=command.librarian_model,
        librarian_role_prompt=command.librarian_role_prompt,
        max_librarian_agents=command.max_librarian_agents,
    )
    return LibrarianExecutionPlan(
        profile=None,
        provider=provider,
        resolution=resolution,
        matched_specialties=(),
    )


def _profile_resolution(
    command: HermesLibrarianAskCommand,
    profile: AgentProfile,
    max_librarian_agents: int | None,
) -> LibrarianProfileResolution:
    provider_id = command.provider_id
    if provider_id is None:
        provider_id = profile.preferred_librarian_provider
    librarian_model = command.librarian_model
    if librarian_model is None:
        librarian_model = profile.preferred_librarian_model
    librarian_role_prompt = command.librarian_role_prompt
    if librarian_role_prompt is None:
        librarian_role_prompt = profile.librarian_role_prompt
    return LibrarianProfileResolution(
        provider_id=provider_id,
        librarian_profile_id=profile.id,
        librarian_model=librarian_model,
        librarian_role_prompt=librarian_role_prompt,
        max_librarian_agents=max_librarian_agents or profile.max_librarian_agents,
    )


def _plan_provider(
    provider_id: str | None,
    provider_by_reference: dict[str, LibrarianProvider],
    executable_providers: list[LibrarianProvider],
) -> LibrarianProvider | None:
    if provider_id is not None:
        return provider_by_reference.get(provider_id)
    if executable_providers:
        return executable_providers[0]
    return None


def _provider_reference_lookup(
    providers: list[LibrarianProvider],
) -> dict[str, LibrarianProvider]:
    lookup: dict[str, LibrarianProvider] = {}
    for provider in providers:
        lookup[provider.id] = provider
        lookup[provider.name] = provider
    return lookup
