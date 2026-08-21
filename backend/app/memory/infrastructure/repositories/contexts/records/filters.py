"""Filter builders for Context Vault repository queries."""

from __future__ import annotations

from datetime import datetime

from app.memory.domain.event_enum.context_enums import ContextKind, ContextScope
from app.memory.infrastructure.models.context_models import ContextORM
from sqlalchemy import Select, bindparam, cast, select
from sqlalchemy.dialects.postgresql import JSONB


def filtered_context_statement(
    kind: ContextKind | None,
    project: str | None,
    scope: ContextScope | None,
    workspace_id: str | None,
    agent_id: str | None,
    user_id: str | None,
    session_id: str | None,
    source_agent: str | None,
    tag: str | None,
    created_after: datetime | None,
    created_before: datetime | None,
    updated_after: datetime | None,
    updated_before: datetime | None,
    include_archived: bool,
) -> Select[tuple[ContextORM]]:
    """Build a filtered context query statement.

    Args:
        kind: Optional context kind filter.
        project: Optional project filter.
        scope: Optional scope filter.
        workspace_id: Optional workspace filter.
        agent_id: Optional agent filter.
        user_id: Optional user filter.
        session_id: Optional session filter.
        source_agent: Optional source-agent filter.
        tag: Optional tag filter.
        created_after: Optional inclusive created-at lower bound.
        created_before: Optional inclusive created-at upper bound.
        updated_after: Optional inclusive updated-at lower bound.
        updated_before: Optional inclusive updated-at upper bound.
        include_archived: Whether archived entries are included.
    Returns:
        SQLAlchemy select statement with requested filters applied.
    """
    statement = select(ContextORM)
    if not include_archived:
        statement = statement.where(ContextORM.is_archived.is_(False))
    if kind is not None:
        statement = statement.where(ContextORM.kind == kind.value)
    if project is not None:
        statement = statement.where(ContextORM.project == project)
    if scope is not None:
        statement = statement.where(ContextORM.scope == scope.value)
    if workspace_id is not None:
        statement = statement.where(ContextORM.workspace_id == workspace_id)
    if agent_id is not None:
        statement = statement.where(ContextORM.agent_id == agent_id)
    if user_id is not None:
        statement = statement.where(ContextORM.user_id == user_id)
    if session_id is not None:
        statement = statement.where(ContextORM.session_id == session_id)
    if source_agent is not None:
        statement = statement.where(ContextORM.source_agent == source_agent)
    if created_after is not None:
        statement = statement.where(ContextORM.created_at >= created_after)
    if created_before is not None:
        statement = statement.where(ContextORM.created_at <= created_before)
    if updated_after is not None:
        statement = statement.where(ContextORM.updated_at >= updated_after)
    if updated_before is not None:
        statement = statement.where(ContextORM.updated_at <= updated_before)
    if tag is not None:
        statement = statement.where(
            cast(ContextORM.tags, JSONB).contains(
                bindparam("context_tag", [tag], type_=JSONB)
            )
        )
    return statement
