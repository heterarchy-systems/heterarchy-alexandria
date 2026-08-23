"""Internal contracts for scope-aware Context recall."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScopeIdentity:
    """Validated scope and identity constraints shared by recall sources."""

    include_scopes: tuple[ContextScope, ...]
    project: str | None
    workspace_id: str | None
    agent_id: str | None
    user_id: str | None
    session_id: str | None

    def sql_parameters(self) -> dict[str, str]:
        """Return bind parameters required by this scope boundary.

        Returns:
            Non-null SQL bind values for the validated boundary.
        """
        candidates = {
            "workspace_id": self.workspace_id,
            "project": (
                self.project if ContextScope.PROJECT in self.include_scopes else None
            ),
            "agent_id": (
                self.agent_id if ContextScope.AGENT in self.include_scopes else None
            ),
            "user_id": (
                self.user_id if ContextScope.USER in self.include_scopes else None
            ),
            "session_id": (
                self.session_id if ContextScope.SESSION in self.include_scopes else None
            ),
        }
        return {
            field_name: field_value
            for field_name, field_value in candidates.items()
            if field_value is not None
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextRecallFilter:
    """Common filters applied consistently by every Context recall source."""

    limit: int
    kind: ContextKind | None
    scope_identity: ScopeIdentity
    lifecycle_statuses: tuple[ContextRecallLifecycleStatus, ...] | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextFtsRecall:
    """FTS query text paired with its validated recall filter."""

    query: str
    recall_filter: ContextRecallFilter


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextVectorRecall:
    """Vector query data paired with its validated recall filter."""

    query_embedding: tuple[float, ...]
    model_name: str
    dimensions: int
    fingerprint_key: str
    recall_filter: ContextRecallFilter


def validated_scope_identity(
    include_scopes: tuple[ContextScope, ...],
    project: str | None,
    workspace_id: str | None,
    agent_id: str | None,
    user_id: str | None,
    session_id: str | None,
) -> ScopeIdentity:
    """Validate required identities and return one recall scope boundary.

    Args:
        include_scopes: Requested recall lanes.
        project: Project identity.
        workspace_id: Workspace identity or legacy null lane.
        agent_id: Agent identity.
        user_id: User identity.
        session_id: Session identity.

    Returns:
        Validated scope and identity boundary.
    """
    if not include_scopes:
        raise ValueError("include_scopes must not be empty")
    missing_codes = [
        error_code
        for scope, identity, error_code in (
            (ContextScope.PROJECT, project, "MISSING_PROJECT"),
            (ContextScope.AGENT, agent_id, "MISSING_AGENT_ID"),
            (ContextScope.SESSION, session_id, "MISSING_SESSION_ID"),
            (ContextScope.USER, user_id, "MISSING_USER_ID"),
        )
        if scope in include_scopes and _normalized_identity(identity) is None
    ]
    if missing_codes:
        raise ValueError(", ".join(missing_codes))
    return ScopeIdentity(
        include_scopes=include_scopes,
        project=_normalized_identity(project),
        workspace_id=_normalized_identity(workspace_id),
        agent_id=_normalized_identity(agent_id),
        user_id=_normalized_identity(user_id),
        session_id=_normalized_identity(session_id),
    )


def _normalized_identity(value: str | None) -> str | None:
    """Execute normalized identity.

    Args:
        value: Value being processed.

    Returns:
        str | None result produced by normalized identity.
    """
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
