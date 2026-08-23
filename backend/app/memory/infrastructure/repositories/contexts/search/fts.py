"""PostgreSQL full-text query helpers for Context Vault retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from sqlalchemy import Select, bindparam, false, func, literal_column, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.memory.domain.contracts.context_recall_contracts import ContextFtsRecall
from app.memory.domain.event_enum.context_enums import ContextRecallLifecycleStatus
from app.memory.infrastructure.models.context_models import ContextChunkORM, ContextORM
from app.memory.infrastructure.repositories.contexts.records.scope_recall_filter import (
    ScopeRecallColumns,
    scope_recall_clause,
)
from app.shared.utils.text_metrics import extract_word_tokens

MAX_FTS_TOKEN_COUNT = 32
MAX_FTS_TOKEN_LENGTH = 64

type ContextFtsRow = tuple[str, str, float]
type ContextFtsStatement = Select[ContextFtsRow]
type ContextFtsParameter = str | int | bool | list[str]


@dataclass(slots=True)
class ContextFtsQuery:
    """SQLAlchemy statement and bind parameters for a context FTS query."""

    statement: ContextFtsStatement
    parameters: Mapping[str, ContextFtsParameter]

    def __post_init__(self) -> None:
        """Freeze SQL bind parameters after query construction."""
        self.parameters = MappingProxyType(dict(self.parameters))


def build_context_fts_query(recall: ContextFtsRecall) -> ContextFtsQuery | None:
    """Build a safe PostgreSQL FTS query from validated recall input.

    Args:
        recall: Validated context recall contract.

    Returns:
        Bound PostgreSQL FTS query, or None when no searchable tokens remain.
    """
    tokens = extract_word_tokens(
        recall.query.strip(),
        max_tokens=MAX_FTS_TOKEN_COUNT,
        max_token_length=MAX_FTS_TOKEN_LENGTH,
    )
    if not tokens:
        return None
    normalized = " & ".join(f"{token}:*" for token in tokens)
    config = literal_column("'simple'")
    empty_text = literal_column("''")
    separator = literal_column("' '")
    query = func.to_tsquery(config, bindparam("query"))
    chunk_document = func.to_tsvector(
        config,
        func.coalesce(ContextChunkORM.heading, empty_text)
        + separator
        + ContextChunkORM.content,
    )
    context_document = func.to_tsvector(
        config,
        ContextORM.title
        + separator
        + ContextORM.summary
        + separator
        + ContextORM.content
        + separator
        + func.coalesce(ContextORM.project, empty_text)
        + separator
        + ContextORM.source_agent,
    )
    rank = cast(
        ColumnElement[float],
        (
            func.ts_rank_cd(chunk_document, query)
            + (func.ts_rank_cd(context_document, query) * 0.5)
        ).label("rank"),
    )
    recall_filter = recall.recall_filter
    storage_statuses = ContextRecallLifecycleStatus.context_storage_values(
        recall_filter.lifecycle_statuses
    )
    lifecycle_conditions: list[ColumnElement[bool]] = []
    parameters: dict[str, ContextFtsParameter] = {
        "query": normalized,
        "limit": recall_filter.limit,
    }
    if storage_statuses:
        lifecycle_conditions.append(
            ContextORM.is_archived.is_(False)
            & ContextORM.status.in_(bindparam("recall_statuses", expanding=True))
        )
        parameters["recall_statuses"] = list(storage_statuses)
    if (
        recall_filter.lifecycle_statuses is not None
        and ContextRecallLifecycleStatus.ARCHIVED in recall_filter.lifecycle_statuses
    ):
        lifecycle_conditions.append(ContextORM.is_archived.is_(True))
    statement = (
        select(ContextChunkORM.id, ContextORM.id, rank)
        .join(ContextORM, ContextORM.id == ContextChunkORM.context_id)
        .where(
            or_(chunk_document.op("@@")(query), context_document.op("@@")(query)),
            or_(*lifecycle_conditions) if lifecycle_conditions else false(),
        )
    )
    identity_filter = recall_filter.scope_identity
    context_table = ContextORM.__table__
    statement = statement.where(
        scope_recall_clause(
            ScopeRecallColumns(
                scope=context_table.c.scope,
                project=context_table.c.project,
                agent_id=context_table.c.agent_id,
                user_id=context_table.c.user_id,
                session_id=context_table.c.session_id,
                workspace_id=context_table.c.workspace_id,
            ),
            identity_filter,
        )
    )
    parameters.update(identity_filter.sql_parameters())
    if recall_filter.kind is not None:
        statement = statement.where(ContextORM.kind == bindparam("kind"))
        parameters["kind"] = recall_filter.kind.value
    statement = statement.order_by(rank.desc()).limit(bindparam("limit"))
    return ContextFtsQuery(
        statement=cast(ContextFtsStatement, statement),
        parameters=parameters,
    )
