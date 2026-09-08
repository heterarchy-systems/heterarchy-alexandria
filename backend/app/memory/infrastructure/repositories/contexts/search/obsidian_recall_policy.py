"""Shared scope, lifecycle, and candidate policies for Obsidian Context recall."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, case, func
from sqlalchemy.sql.elements import ColumnElement

from app.memory.domain.contracts.context_recall_contracts import (
    ScopeIdentity,
)
from app.memory.domain.event_enum.context_enums import (
    ContextRecallLifecycleStatus,
    ContextScope,
)
from app.memory.infrastructure.repositories.contexts.records.scope_recall_filter import (
    ScopeRecallColumns,
    scope_recall_clause,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianFileORM,
)
from app.shared.types.extra_types import JSONObject

OBSIDIAN_MATCH_LIMIT_MULTIPLIER = 4


def _candidate_limit(limit: int) -> int:
    """Execute candidate limit.

    Args:
        limit: Maximum number of items to process or return.

    Returns:
        int result produced by candidate limit.
    """
    return max(limit, limit * OBSIDIAN_MATCH_LIMIT_MULTIPLIER)


def _obsidian_scope_recall_clause(
    frontmatter_column: ColumnElement[JSONObject],
    project_column: ColumnElement[str | None],
    note_type_column: ColumnElement[str],
    scope_filter: ScopeIdentity,
) -> ColumnElement[bool]:
    """Execute obsidian scope recall clause.

    Args:
        frontmatter_column: Frontmatter column used by this operation.
        project_column: Project column used by this operation.
        note_type_column: Alexandria note type column used by this operation.
        scope_filter: Scope filter used by this operation.

    Returns:
        ColumnElement[bool] result produced by obsidian scope recall clause.
    """

    def extract(key: str) -> ColumnElement[str | None]:
        """Execute extract.

        Args:
            key: Key used by this operation.

        Returns:
            ColumnElement[str | None] result produced by extract.
        """
        return func.json_extract_path_text(frontmatter_column, key)

    scope_column = func.upper(func.nullif(func.trim(extract("scope")), ""))
    normalized_project = func.nullif(func.trim(project_column), "")
    effective_scope_column = case(
        (
            and_(
                note_type_column != AlexandriaNoteType.CONTEXT.value,
                scope_column.is_(None),
                normalized_project.is_not(None),
            ),
            ContextScope.PROJECT.value,
        ),
        (
            and_(
                note_type_column != AlexandriaNoteType.CONTEXT.value,
                scope_column.is_(None),
                normalized_project.is_(None),
            ),
            ContextScope.GLOBAL.value,
        ),
        else_=scope_column,
    )
    workspace_id_column = extract("workspace_id")
    agent_id_column = extract("agent_id")
    user_id_column = extract("user_id")
    session_id_column = extract("session_id")
    return scope_recall_clause(
        ScopeRecallColumns(
            scope=effective_scope_column,
            project=normalized_project,
            agent_id=agent_id_column,
            user_id=user_id_column,
            session_id=session_id_column,
            workspace_id=workspace_id_column,
        ),
        scope_filter,
    )


def _recall_visibility_conditions(
    include_lifecycle_statuses: Sequence[ContextRecallLifecycleStatus] | None,
) -> tuple[ColumnElement[bool], ...]:
    """Execute recall visibility conditions.

    Args:
        include_lifecycle_statuses: Whether to include lifecycle statuses.

    Returns:
        tuple[ColumnElement[bool], ...] result produced by recall visibility conditions.
    """
    normalized_status = func.coalesce(
        func.nullif(func.lower(func.trim(ObsidianFileORM.status)), ""),
        "active",
    )
    return (
        ObsidianFileORM.index_status == ObsidianIndexStatus.INDEXED.value,
        normalized_status.in_(
            ContextRecallLifecycleStatus.obsidian_values(include_lifecycle_statuses)
        ),
        ~ObsidianFileORM.relative_path.like("\\_Ops/%", escape="\\"),
    )


def _default_recall_visibility_conditions() -> tuple[ColumnElement[bool], ...]:
    """Execute default recall visibility conditions.

    Returns:
        tuple[ColumnElement[bool], ...] result produced by default recall visibility conditions.
    """
    return _recall_visibility_conditions(None)
