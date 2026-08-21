"""PostgreSQL search SQL compilation contracts."""

from __future__ import annotations

from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
    ContextRecallFilter,
    ContextVectorRecall,
    ScopeIdentity,
)
from app.memory.domain.event_enum.context_enums import (
    ContextRecallLifecycleStatus,
    ContextScope,
)
from app.memory.infrastructure.repositories.contexts.embeddings.vector_query import (
    build_context_vector_query,
)
from app.memory.infrastructure.repositories.contexts.search.fts import (
    build_context_fts_query,
)
from app.obsidian.infrastructure.repositories.obsidian_fts import (
    build_obsidian_fts_query,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ClauseElement


def _recall_filter() -> ContextRecallFilter:
    return ContextRecallFilter(
        limit=5,
        kind=None,
        scope_identity=ScopeIdentity(
            include_scopes=(ContextScope.PROJECT,),
            project="heterarchy-alexandria",
            workspace_id=None,
            agent_id=None,
            user_id=None,
            session_id=None,
        ),
        lifecycle_statuses=(ContextRecallLifecycleStatus.ACTIVE,),
    )


def _compile(statement: ClauseElement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_postgres_context_fts_matches_expression_index_shape() -> None:
    """Context FTS SQL should use literal-stable indexed expressions."""
    query = build_context_fts_query(
        ContextFtsRecall(query="운영 안정성", recall_filter=_recall_filter()),
    )

    assert query is not None
    sql = _compile(query.statement)
    lowered = sql.lower()

    assert "to_tsvector('simple'" in sql
    assert "to_tsquery('simple'" in sql
    assert "ts_rank_cd" in sql
    assert (
        "coalesce(context_chunks.heading, '') || ' ' || context_chunks.content" in sql
    )
    assert "match" not in lowered
    assert "bm25" not in lowered
    assert "json_extract(" not in lowered


def test_postgres_context_vector_uses_exact_pgvector_cosine_distance() -> None:
    """Initial vector retrieval should use exact pgvector search without ANN SQL."""
    query = build_context_vector_query(
        ContextVectorRecall(
            query_embedding=(0.1,) * 384,
            model_name="test-model",
            dimensions=384,
            fingerprint_key="test-fingerprint",
            recall_filter=_recall_filter(),
        ),
    )
    sql = _compile(query.statement)
    lowered = sql.lower()

    assert "context_chunks.embedding <=>" in sql
    assert "order by distance asc" in lowered
    assert "vec_distance_cosine" not in lowered


def test_postgres_obsidian_fts_uses_base_tables_and_jsonb_tags() -> None:
    """Obsidian search should avoid SQLite virtual tables on PostgreSQL."""
    query = build_obsidian_fts_query(
        "운영 안정성",
        limit=5,
        project="heterarchy-alexandria",
        tags=("evidence",),
    )

    assert query is not None
    sql = _compile(query.statement)
    lowered = sql.lower()

    assert "from obsidian_chunks join obsidian_files" in lowered
    assert (
        "coalesce(obsidian_chunks.heading_path, '') || ' ' || obsidian_chunks.text"
        in sql
    )
    assert "cast(obsidian_files.tags as jsonb) @>" in lowered
    assert "lower(trim(obsidian_files.title))" in lowered
    assert "union" in lowered
    assert "obsidian_fts_candidates" in lowered
    assert query.parameters["exact_title"] == "운영 안정성"
    assert "obsidian_chunk_fts" not in lowered
    assert "json_each" not in lowered
    assert "match" not in lowered
