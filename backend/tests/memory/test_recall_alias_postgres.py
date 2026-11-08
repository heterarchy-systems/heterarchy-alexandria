"""Real PostgreSQL alias recall and malformed-frontmatter regressions."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter_ns

import anyio
from sqlalchemy import event, text
from tests.memory.context_retrieval_kernel_test_provider import (
    TestContextRetrievalKernelProvider,
)

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
)
from app.memory.application.retrieval.recall.recall_service import RecallService
from app.memory.domain.contracts.recall_contracts import RecallRequest
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.event_enum.recall_enums import RecallOutcome, RecallScopeMode
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.memory.infrastructure.repositories.contexts.search.obsidian_search_source import (
    SqlAlchemyObsidianContextSearchSource,
)
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.repositories.obsidian_fts import (
    build_obsidian_fts_query,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.infrastructure.database import Database
from app.shared.types.extra_types import JSONValue


class _ExactEmpty:
    """Typed exact resolver fake for alias routing tests."""

    async def resolve(
        self,
        selector: object,
        scope_identity: object,
    ) -> tuple[ContextSearchMatch, ...]:
        del selector, scope_identity
        return ()


async def _save_note(
    service: ObsidianService,
    *,
    note_id: str,
    project: str,
    aliases: JSONValue,
    relative_path: str,
) -> None:
    await service.save_note(
        ObsidianSaveNote(
            title="Canonical Architecture Note",
            body="# Canonical Architecture Note\n\nBody has no alias text.",
            alexandria_type=AlexandriaNoteType.CONTEXT,
            note_id=note_id,
            project=project,
            relative_path=relative_path,
            frontmatter={"scope": "PROJECT", "aliases": aliases},
        )
    )


def test_real_postgres_alias_recall_scope_and_malformed_alias_safety(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[
        RecallOutcome,
        str | None,
        tuple[str, ...],
        RecallOutcome,
        dict[str, dict[str, object]],
    ]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.session() as session:
                obsidian_service = ObsidianService(
                    repository=SqlAlchemyObsidianIndexRepository(session=session),
                    vault_path=str(tmp_path / "vault"),
                    alexandria_root="Alexandria",
                )
                await _save_note(
                    obsidian_service,
                    note_id="alias-primary",
                    project="alias-primary",
                    aliases=["  Rare Alias  "],
                    relative_path="Alexandria/Contexts/Alias Primary.md",
                )
                await _save_note(
                    obsidian_service,
                    note_id="alias-private",
                    project="other-project",
                    aliases=["Rare Alias"],
                    relative_path="Alexandria/Contexts/Alias Private.md",
                )
                await _save_note(
                    obsidian_service,
                    note_id="alias-malformed",
                    project="alias-primary",
                    aliases={"unexpected": "object"},
                    relative_path="Alexandria/Contexts/Alias Malformed.md",
                )
                await session.commit()
                context_service = ContextService(
                    repository=SqlAlchemyContextRepository(session=session),
                    retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                    extra_search_sources=[
                        SqlAlchemyObsidianContextSearchSource(session=session)
                    ],
                )
                temporal_service = MemoryTemporalRecallService(
                    context_service=context_service,
                    repository=SqlAlchemyMemoryReconciliationRepository(session),
                )
                recall_service = RecallService(
                    context_service=context_service,
                    temporal_recall_service=temporal_service,
                    exact_selector_resolver=_ExactEmpty(),
                )
                recalled = await recall_service.recall(
                    RecallRequest(
                        query="rare alias",
                        project="alias-primary",
                        scope_mode=RecallScopeMode.STRICT,
                        include_scopes=(ContextScope.PROJECT,),
                    )
                )
                malformed = await recall_service.recall(
                    RecallRequest(
                        query="malformed alias",
                        project="alias-primary",
                        scope_mode=RecallScopeMode.STRICT,
                        include_scopes=(ContextScope.PROJECT,),
                    )
                )

                async def measure_fts(query: str) -> dict[str, object]:
                    for _ in range(2):
                        await context_service.search(
                            query=query,
                            strategy=RagStrategy.FTS_ONLY,
                            limit=3,
                            project="alias-primary",
                            include_scopes=[ContextScope.PROJECT],
                        )
                    sql_statements = 0
                    elapsed_ms: list[float] = []

                    def count_sql(
                        _connection: object,
                        _cursor: object,
                        statement: str,
                        _parameters: object,
                        _context: object,
                        _executemany: bool,
                    ) -> None:
                        nonlocal sql_statements
                        if "obsidian_files" in statement.casefold():
                            sql_statements += 1

                    event.listen(
                        database.engine.sync_engine,
                        "before_cursor_execute",
                        count_sql,
                    )
                    try:
                        for _ in range(20):
                            started = perf_counter_ns()
                            await context_service.search(
                                query=query,
                                strategy=RagStrategy.FTS_ONLY,
                                limit=3,
                                project="alias-primary",
                                include_scopes=[ContextScope.PROJECT],
                            )
                            elapsed_ms.append((perf_counter_ns() - started) / 1_000_000)
                    finally:
                        event.remove(
                            database.engine.sync_engine,
                            "before_cursor_execute",
                            count_sql,
                        )
                    return {
                        "samples": 20,
                        "sql_statements": sql_statements,
                        "p50_ms": median(elapsed_ms),
                        "p95_ms": sorted(elapsed_ms)[18],
                    }

                metrics = {
                    "alias": await measure_fts("rare alias"),
                    "control": await measure_fts("unmatched alias token"),
                }
                return (
                    recalled.outcome,
                    recalled.matches[0].provenance.title_alias_contribution
                    if recalled.matches
                    else None,
                    tuple(item.match.context.id for item in recalled.matches),
                    malformed.outcome,
                    metrics,
                )
        finally:
            await database.shutdown()

    outcome, contribution, ids, malformed_outcome, metrics = anyio.run(scenario)
    assert outcome is RecallOutcome.MATCHED
    assert contribution == "ALIAS"
    assert ids == ("obsidian:alias-primary",)
    assert malformed_outcome in {
        RecallOutcome.SEARCH_EXHAUSTED,
        RecallOutcome.NO_CONFIDENT_MATCH,
        RecallOutcome.DEGRADED_SEARCH,
    }
    Path("/tmp/alexandria-alias-after-fixture.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def test_postgres_fts_preserves_candidate_chunks_ranks_and_filters() -> None:
    """Reuse note scores without losing chunk-only or note-wide matches."""

    async def scenario() -> None:
        database = Database(os.environ["DATABASE_URL"], create_schema=True)
        await database.initialize()
        now = datetime(2026, 10, 22, tzinfo=UTC)
        try:
            async with database.session() as session:
                for note_id in (
                    "lexical",
                    "title",
                    "alias",
                    "chunk",
                    "excluded",
                    "untagged",
                    "wrong-kind",
                    "archived",
                    "not-indexed",
                    "miss",
                ):
                    boosted = note_id in {
                        "title",
                        "excluded",
                        "untagged",
                        "wrong-kind",
                        "archived",
                        "not-indexed",
                    }
                    session.add(
                        ObsidianFileORM(
                            note_id=note_id,
                            relative_path=f"Alexandria/{note_id}.md",
                            alexandria_type="skill"
                            if note_id == "wrong-kind"
                            else "context",
                            title="Evidence Intelligence" if boosted else "General",
                            status="archived" if note_id == "archived" else "current",
                            tags=["other"] if note_id == "untagged" else ["evidence"],
                            project="other" if note_id == "excluded" else "project-a",
                            content_hash="a" * 64,
                            frontmatter_json={"aliases": [" EVIDENCE   intelligence "]}
                            if note_id == "alias"
                            else {},
                            body="Evidence Intelligence source."
                            if note_id == "lexical"
                            else "Unrelated durable content.",
                            index_status="error"
                            if note_id == "not-indexed"
                            else "indexed",
                            size_bytes=100,
                            modified_at=now,
                            indexed_at=now,
                        )
                    )
                    await session.flush()
                    for index in range(2):
                        session.add(
                            ObsidianChunkORM(
                                id=f"{note_id}-{index}",
                                note_id=note_id,
                                chunk_index=index,
                                heading_path=None,
                                text="Evidence Intelligence"
                                if index == 0 and note_id in {"lexical", "chunk"}
                                else "Unrelated chunk.",
                                token_count=2,
                                content_hash="b" * 64,
                                created_at=now,
                            )
                        )
                await session.commit()
                for filtered in (False, True):
                    query = build_obsidian_fts_query(
                        "Evidence Intelligence",
                        limit=100,
                        project="project-a" if filtered else None,
                        alexandria_type=AlexandriaNoteType.CONTEXT
                        if filtered
                        else None,
                        tags=("evidence",) if filtered else None,
                        included_statuses=["current"] if filtered else None,
                    )
                    assert query is not None
                    actual = (
                        await session.execute(query.statement, dict(query.parameters))
                    ).all()
                    # Independent direct scoring reference over this fixture's known candidates.
                    expected = (
                        await session.execute(
                            text("""
                        SELECT c.id,
                            ts_rank_cd(to_tsvector('simple', coalesce(c.heading_path, '') || ' ' || c.text),
                                to_tsquery('simple', 'Evidence:* & Intelligence:*'))
                            + ts_rank_cd(to_tsvector('simple', f.title || ' ' || f.body || ' ' ||
                                coalesce(f.project, '') || ' ' || f.relative_path),
                                to_tsquery('simple', 'Evidence:* & Intelligence:*')) * 0.5::double precision
                            + CASE WHEN lower(trim(f.title)) = 'evidence intelligence'
                                THEN 1.0::double precision ELSE 0.0 END
                            + CASE WHEN f.note_id = 'alias'
                                THEN 1.0::double precision ELSE 0.0 END AS rank
                        FROM obsidian_chunks c JOIN obsidian_files f ON f.note_id = c.note_id
                        WHERE f.index_status = 'indexed' AND f.note_id <> 'miss'
                            AND (f.note_id <> 'chunk' OR c.chunk_index = 0)
                            AND (NOT :filtered OR (f.project = 'project-a' AND
                                f.alexandria_type = 'context' AND f.status = 'current'
                                AND f.tags::jsonb @> '["evidence"]'::jsonb))
                    """),
                            {"filtered": filtered},
                        )
                    ).all()
                    assert {row.id: row.rank for row in actual} == dict(expected)
                    assert len(actual) == (7 if filtered else 15)
                    assert [row.rank for row in actual] == sorted(
                        (row.rank for row in actual), reverse=True
                    )
        finally:
            await database.shutdown()

    anyio.run(scenario)
