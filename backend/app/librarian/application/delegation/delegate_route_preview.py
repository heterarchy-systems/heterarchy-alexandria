"""Public route preview policy for librarian delegation."""

from __future__ import annotations

from app.librarian.application.delegation.delegate_execution_contracts import (
    LibrarianExecutionPlan,
)
from app.librarian.application.routing.profile_routing_contracts import (
    LibrarianRoutingDecision,
)


def build_route_preview(
    representative_plan: LibrarianExecutionPlan | None,
    routing: LibrarianRoutingDecision,
    delegated: bool,
    executable_count: int,
) -> list[str]:
    """Create human-readable routing evidence for the ask response.

    Args:
        representative_plan: Plan used for top-level provider/profile fields.
        routing: Selected profiles and matching evidence.
        delegated: Whether delegates were executed.
        executable_count: Number of executable plans.

    Returns:
        list[str]: Ordered route-preview messages.
    """
    preview = ["Hermes direct search first"]
    if not routing.selected_profiles:
        preview.append("No librarian profiles configured")
    else:
        selected = ", ".join(profile.id for profile in routing.selected_profiles)
        preview.append(f"Selected profiles: {selected}")
    if routing.matched_specialties:
        preview.append(f"Matched specialties: {', '.join(routing.matched_specialties)}")
    preview.append(f"Routing reason: {routing.reason}")
    if representative_plan is None or representative_plan.provider is None:
        preview.append("No executable librarian provider available")
        preview.append("Hermes self-acquisition path")
        return preview
    preview.append(f"Specialized librarian provider: {representative_plan.provider.id}")
    if delegated:
        if executable_count <= 0:
            preview.append("No delegated librarians completed")
            return preview
        preview.append(f"Completed delegated librarians: {executable_count}")
    else:
        preview.append("Preview only; no librarian delegation queued")
    return preview
