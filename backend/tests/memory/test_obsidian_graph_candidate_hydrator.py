"""PostgreSQL integration contracts for graph-selected Obsidian Context hydration."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import anyio

from app.memory.domain.contracts.context_recall_contracts import (
    ContextRecallFilter,
    ScopeIdentity,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.infrastructure.repositories.contexts.obsidian.obsidian_graph_candidate_hydrator import (
    ObsidianGraphCandidateHydrator,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)
from app.shared.infrastructure.database import Database

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def test_graph_candidate_hydrator_preserves_selection_order_filters_scope_and_uses_first_nonempty_chunk(
    tmp_path: Path,
) -> None:
    del tmp_path

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.session() as session:
                session.add_all(
                    [
                        _note("alpha-a", project="alpha", status="active"),
                        _note("alpha-b", project="alpha", status="active"),
                        _note("beta", project="beta", status="active"),
                        _note("old", project="alpha", status="superseded"),
                    ]
                )
                await session.flush()
                session.add_all(
                    [
                        _chunk("a-blank", "alpha-a", 0, "   "),
                        _chunk("a-first", "alpha-a", 1, "first meaningful A"),
                        _chunk("a-later", "alpha-a", 2, "later A"),
                        _chunk("b-first", "alpha-b", 0, "first B"),
                        _chunk("beta-first", "beta", 0, "beta body"),
                        _chunk("old-first", "old", 0, "old body"),
                    ]
                )
                await session.flush()
                hydrator = ObsidianGraphCandidateHydrator(session)
                hydrated = await hydrator.hydrate(
                    ("alpha-b", "beta", "alpha-a", "old"),
                    _recall_filter(),
                )
                assert [item.note_id for item in hydrated] == ["alpha-b", "alpha-a"]
                assert [item.context.id for item in hydrated] == [
                    "obsidian:alpha-b",
                    "obsidian:alpha-a",
                ]
                assert hydrated[0].chunk.content == "first B"
                assert hydrated[0].chunk.chunk_index == 0
                assert hydrated[1].chunk.content == "first meaningful A"
                assert hydrated[1].chunk.chunk_index == 1
                assert hydrated[1].context.project == "alpha"
        finally:
            await database.shutdown()

    anyio.run(scenario)


def test_graph_candidate_hydrator_rejects_unbounded_candidate_lists() -> None:
    class _NeverUsedSession:
        pass

    hydrator = ObsidianGraphCandidateHydrator(_NeverUsedSession())  # type: ignore[arg-type]

    async def scenario() -> None:
        try:
            await hydrator.hydrate(
                tuple(f"note-{index}" for index in range(9)), _recall_filter()
            )
        except ValueError as exc:
            assert "GRAPH_CANDIDATE_HYDRATION_LIMIT_EXCEEDED" in str(exc)
        else:
            raise AssertionError(
                "unbounded graph hydration must fail before database access"
            )

    anyio.run(scenario)


def _recall_filter() -> ContextRecallFilter:
    return ContextRecallFilter(
        limit=5,
        kind=None,
        scope_identity=ScopeIdentity(
            include_scopes=(ContextScope.PROJECT,),
            project="alpha",
            workspace_id=None,
            agent_id=None,
            user_id=None,
            session_id=None,
        ),
        lifecycle_statuses=None,
    )


def _note(note_id: str, project: str, status: str) -> ObsidianFileORM:
    return ObsidianFileORM(
        note_id=note_id,
        relative_path=f"Contexts/{note_id}.md",
        alexandria_type=AlexandriaNoteType.JOB_PLAN.value,
        title=note_id.replace("-", " ").title(),
        status=status,
        tags=[],
        project=project,
        source="test",
        content_hash=f"hash-{note_id}",
        frontmatter_json={"scope": "PROJECT", "visibility": "PROJECT"},
        body=f"body {note_id}",
        index_status=ObsidianIndexStatus.INDEXED.value,
        error_message=None,
        size_bytes=16,
        modified_at=NOW,
        indexed_at=NOW,
    )


def _chunk(
    chunk_id: str,
    note_id: str,
    chunk_index: int,
    text: str,
) -> ObsidianChunkORM:
    return ObsidianChunkORM(
        id=chunk_id,
        note_id=note_id,
        chunk_index=chunk_index,
        heading_path=None,
        text=text,
        token_count=max(1, len(text.split())),
        content_hash=f"hash-{chunk_id}",
        embedding=None,
        embedding_model=None,
        embedding_dimensions=None,
        embedding_provider=None,
        embedding_provider_version=None,
        embedding_pooling_mode=None,
        embedding_normalize=None,
        embedding_fingerprint_key=None,
        embedding_fingerprint_json=None,
        embedding_indexed_at=None,
        created_at=NOW,
    )
