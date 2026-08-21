"""Projection source snapshots built from the rebuildable Obsidian index."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from app.obsidian.application.graph.projection.obsidian_graph_projection_source_builder import (
    ObsidianGraphProjectionSourceBuilder,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphProjectionIssueCode,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianIndexStatus,
)
from app.obsidian.infrastructure.graph.sqlalchemy_obsidian_graph_projection_source import (
    SqlAlchemyObsidianGraphProjectionSource,
)
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianEdgeORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.repositories.obsidian_index_mapping import (
    edge_from_model,
    note_from_model,
)
from app.shared.infrastructure.database import Database
from sqlalchemy import func, select

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models
_NOW = datetime(2026, 8, 3, tzinfo=UTC)


def _note(
    note_id: str,
    *,
    index_status: ObsidianIndexStatus = ObsidianIndexStatus.INDEXED,
    error_message: str | None = None,
) -> ObsidianFileORM:
    return ObsidianFileORM(
        note_id=note_id,
        relative_path=f"Alexandria/Contexts/{note_id}.md",
        alexandria_type="context",
        title=note_id,
        status="active",
        tags=[],
        project="heterarchy-alexandria",
        source="test",
        content_hash=f"hash-{note_id}",
        frontmatter_json={},
        body=f"# {note_id}",
        index_status=index_status.value,
        error_message=error_message,
        size_bytes=10,
        modified_at=_NOW,
        indexed_at=_NOW,
    )


def _edge(
    edge_id: str,
    *,
    source_note_id: str,
    target_note_id: str | None,
    target_path: str,
) -> ObsidianEdgeORM:
    return ObsidianEdgeORM(
        edge_id=edge_id,
        source_note_id=source_note_id,
        source_path=f"Alexandria/Contexts/{source_note_id}.md",
        target_note_id=target_note_id,
        target_path=target_path,
        relation="related",
        confidence=0.8,
        source_kind="frontmatter",
        created_at=_NOW,
        indexed_at=_NOW,
    )


def test_builder_returns_deterministic_typed_batches_from_postgresql_index(
    tmp_path: Path,
) -> None:
    """Only healthy indexed rows should appear in stable projection batches."""

    async def scenario():
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        try:
            session.add_all(
                [
                    _note("note-z"),
                    _note(
                        "note-error",
                        index_status=ObsidianIndexStatus.ERROR,
                        error_message="frontmatter validation failed",
                    ),
                    _note("note-a"),
                    _note("note-stale", index_status=ObsidianIndexStatus.STALE),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    _edge(
                        "edge-z",
                        source_note_id="note-z",
                        target_note_id="note-a",
                        target_path="old/path.md",
                    ),
                    _edge(
                        "edge-a",
                        source_note_id="note-a",
                        target_note_id=None,
                        target_path="Missing.md",
                    ),
                ]
            )
            await session.commit()
            before = (
                await session.scalar(select(func.count()).select_from(ObsidianFileORM)),
                await session.scalar(select(func.count()).select_from(ObsidianEdgeORM)),
            )
            builder = ObsidianGraphProjectionSourceBuilder(
                source=SqlAlchemyObsidianGraphProjectionSource(session=session),
                batch_size=1,
            )
            first = await builder.build()
            second = await builder.build()
            after = (
                await session.scalar(select(func.count()).select_from(ObsidianFileORM)),
                await session.scalar(select(func.count()).select_from(ObsidianEdgeORM)),
            )
            assert before == after
            return first, second, (int(after[0] or 0), int(after[1] or 0))
        finally:
            await session.close()
            await database.shutdown()

    first, second, row_counts = anyio.run(scenario)

    assert first == second
    assert row_counts == (4, 2)
    assert not (tmp_path / "vault").exists()
    assert tuple(node.note_id for node in first.projection.nodes) == (
        "note-a",
        "note-z",
    )
    assert tuple(edge.edge_id for edge in first.projection.edges) == ("edge-z",)
    assert first.projection.edges[0].target_note_id == "note-a"
    assert first.projection.edges[0].target_path == ("Alexandria/Contexts/note-a.md")
    assert tuple(batch.batch_index for batch in first.batches) == (0, 1)
    assert all(len(batch.projection.nodes) <= 1 for batch in first.batches)
    assert all(len(batch.projection.edges) <= 1 for batch in first.batches)
    assert tuple(issue.code for issue in first.issues) == (
        ObsidianGraphProjectionIssueCode.INDEX_ERROR,
        ObsidianGraphProjectionIssueCode.MISSING_TARGET_NOTE,
    )
    assert first.issues[0].note_id == "note-error"
    assert first.issues[1].note_id == "note-a"
    assert first.issues[1].relative_path == "Missing.md"
    assert first.issues[1].edge_id == "edge-a"
    assert first.metrics.scanned == 6
    assert first.metrics.indexed == 3
    assert first.metrics.skipped == 3
    assert first.metrics.errors == 2


def test_builder_resolves_unique_obsidian_filename_targets() -> None:
    """A unique filename match should resolve bare/source-relative wikilink paths."""

    async def scenario():
        class _Source:
            async def list_projection_notes(self) -> tuple[object, ...]:
                target = _note("target")
                target.relative_path = "Alexandria/Skills/Active/Target.md"
                target.title = "Target"
                return (
                    note_from_model(_note("source")),
                    note_from_model(target),
                )

            async def list_projection_edges(self) -> tuple[object, ...]:
                return (
                    edge_from_model(
                        _edge(
                            "edge-bare",
                            source_note_id="source",
                            target_note_id=None,
                            target_path="Alexandria/Contexts/Target.md",
                        )
                    ),
                )

        return await ObsidianGraphProjectionSourceBuilder(source=_Source()).build()

    snapshot = anyio.run(scenario)

    assert snapshot.projection.edges[0].target_note_id == "target"
    assert snapshot.projection.edges[0].target_path == (
        "Alexandria/Skills/Active/Target.md"
    )
    assert snapshot.issues == ()


def test_builder_rejects_non_positive_batch_size() -> None:
    """A batch size must be positive before the source is queried."""
    with pytest.raises(ValueError, match="batch_size must be greater than zero"):
        ObsidianGraphProjectionSourceBuilder(source=None, batch_size=0)
