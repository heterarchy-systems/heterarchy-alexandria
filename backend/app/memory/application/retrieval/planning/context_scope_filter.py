"""Apply validated scope identity boundaries to Context recall matches."""

from __future__ import annotations

from app.memory.domain.contracts.context_recall_contracts import ScopeIdentity
from app.memory.domain.entities.context_read_models import (
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import ContextScope


def context_matches_scope(
    context: ContextRecord,
    scope_filter: ScopeIdentity,
) -> bool:
    """Return whether one Context belongs to a requested scope lane.

    Args:
        context: Retrieved Context to validate.
        scope_filter: Validated recall scope and identity constraints.

    Returns:
        Whether the Context belongs to the requested scope lane.
    """
    if context.workspace_id != scope_filter.workspace_id:
        return False
    scope_value = context.scope
    if scope_value not in scope_filter.include_scopes:
        return False
    if scope_value is ContextScope.GLOBAL:
        return True
    if scope_value is ContextScope.PROJECT:
        return context.project == scope_filter.project
    if scope_value is ContextScope.AGENT:
        return context.agent_id == scope_filter.agent_id
    if scope_value is ContextScope.SESSION:
        return context.session_id == scope_filter.session_id
    if scope_value is ContextScope.USER:
        return context.user_id == scope_filter.user_id
    return False


def filter_context_matches(
    matches: list[ContextSearchMatch],
    scope_filter: ScopeIdentity | None,
) -> list[ContextSearchMatch]:
    """Revalidate retrieval results at the final aggregation boundary.

    Args:
        matches: Retrieval matches produced by one or more search sources.
        scope_filter: Validated recall scope and identity constraints, if any.

    Returns:
        Matches that remain inside the requested scope boundary.
    """
    if scope_filter is None:
        return matches
    return [
        match for match in matches if context_matches_scope(match.context, scope_filter)
    ]
