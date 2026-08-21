"""Shared scope, lifecycle, and candidate policies for Obsidian Context recall."""

from __future__ import annotations

from collections.abc import Sequence

from app.memory.domain.contracts.context_recall_contracts import (
    ScopeIdentity,
)
from app.memory.domain.event_enum.context_enums import (
    ContextRecallLifecycleStatus,
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
from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

OBSIDIAN_MATCH_LIMIT_MULTIPLIER = 4


def _candidate_limit(limit: int) -> int:
    return max(limit, limit * OBSIDIAN_MATCH_LIMIT_MULTIPLIER)


def _obsidian_scope_recall_clause(
    frontmatter_column: ColumnElement[JSONObject],
    project_column: ColumnElement[str | None],
    scope_filter: ScopeIdentity,
) -> ColumnElement[bool]:
    def extract(key: str) -> ColumnElement[str | None]:
        return func.json_extract_path_text(frontmatter_column, key)

    scope_column = func.upper(extract("scope"))
    workspace_id_column = extract("workspace_id")
    agent_id_column = extract("agent_id")
    user_id_column = extract("user_id")
    session_id_column = extract("session_id")
    return scope_recall_clause(
        ScopeRecallColumns(
            scope=scope_column,
            project=project_column,
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
    normalized_status = func.coalesce(
        func.nullif(func.lower(func.trim(ObsidianFileORM.status)), ""),
        "active",
    )
    return (
        ObsidianFileORM.index_status == ObsidianIndexStatus.INDEXED.value,
        ObsidianFileORM.alexandria_type != AlexandriaNoteType.LIBRARIAN_CHAT.value,
        normalized_status.in_(
            ContextRecallLifecycleStatus.obsidian_values(include_lifecycle_statuses)
        ),
        ~ObsidianFileORM.relative_path.like("\\_Ops/%", escape="\\"),
    )


def _default_recall_visibility_conditions() -> tuple[ColumnElement[bool], ...]:
    return _recall_visibility_conditions(None)
