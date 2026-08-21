"""Build scope-aware SQL filters for Context recall."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.domain.contracts.context_recall_contracts import ScopeIdentity
from app.memory.domain.event_enum.context_enums import ContextScope
from sqlalchemy import and_, bindparam, or_
from sqlalchemy.sql.elements import ColumnElement


@dataclass(frozen=True, slots=True, kw_only=True)
class ScopeRecallColumns:
    """SQL columns participating in one scope-aware recall boundary."""

    scope: ColumnElement[str]
    project: ColumnElement[str | None]
    agent_id: ColumnElement[str | None]
    user_id: ColumnElement[str | None]
    session_id: ColumnElement[str | None]
    workspace_id: ColumnElement[str | None]


def scope_recall_clause(
    columns: ScopeRecallColumns,
    identity_filter: ScopeIdentity,
) -> ColumnElement[bool]:
    """Build a disjunctive scope/identity recall boundary.

    Args:
        columns: Cohesive SQL columns for scope and identity matching.
        identity_filter: Validated scope and identity filter.
    Returns:
        SQLAlchemy boolean clause matching only requested scope lanes.
    """
    clauses: list[ColumnElement[bool]] = []
    for scope_value in identity_filter.include_scopes:
        if scope_value is ContextScope.GLOBAL:
            clauses.append(columns.scope == ContextScope.GLOBAL.value)
        elif scope_value is ContextScope.PROJECT:
            clauses.append(
                and_(
                    columns.scope == ContextScope.PROJECT.value,
                    columns.project == bindparam("project"),
                )
            )
        elif scope_value is ContextScope.AGENT:
            clauses.append(
                and_(
                    columns.scope == ContextScope.AGENT.value,
                    columns.agent_id == bindparam("agent_id"),
                )
            )
        elif scope_value is ContextScope.SESSION:
            clauses.append(
                and_(
                    columns.scope == ContextScope.SESSION.value,
                    columns.session_id == bindparam("session_id"),
                )
            )
        elif scope_value is ContextScope.USER:
            clauses.append(
                and_(
                    columns.scope == ContextScope.USER.value,
                    columns.user_id == bindparam("user_id"),
                )
            )
    scope_clause = clauses[0] if len(clauses) == 1 else or_(*clauses)
    if identity_filter.workspace_id is None:
        legacy_workspace_clause = or_(
            columns.workspace_id.is_(None),
            columns.workspace_id == "",
        )
        return and_(legacy_workspace_clause, scope_clause)
    return and_(
        columns.workspace_id == bindparam("workspace_id"),
        scope_clause,
    )
