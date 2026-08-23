"""Obsidian edge index and related-note retrieval behavior tests."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.models.obsidian_index_models import ObsidianEdgeORM
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


async def _services(
    tmp_path: Path,
) -> tuple[Database, AsyncSession, ObsidianService]:
    database = Database(database_url=_database_url(), create_schema=True)
    await database.initialize()
    session = database.session()
    repository = SqlAlchemyObsidianIndexRepository(session=session)
    obsidian = ObsidianService(
        repository=repository,
        vault_path=str(tmp_path / "vault"),
        alexandria_root="Alexandria",
    )
    return database, session, obsidian


def test_reindex_builds_postgres_edge_source_cache_from_markdown(
    tmp_path: Path,
) -> None:
    """Reindex should retain PostgreSQL edge rows as the Neo4j rebuild source."""

    async def scenario() -> tuple[list[tuple[str, str, str]], str]:
        database, session, obsidian = await _services(tmp_path)
        try:
            start = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Alexandria START HERE",
                    body="# Start\n\nCanonical root note.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="alexandria_start_here",
                    relative_path="Alexandria/START_HERE.md",
                    tags=["start"],
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            current = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Graph Current",
                    body="# Graph Current\n\nThis cites [[START_HERE]].",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_graph_current",
                    frontmatter={
                        "scope": "GLOBAL",
                        "source_refs": [
                            {
                                "id": start.note_id,
                                "path": "START_HERE.md",
                                "relation": "cites",
                            }
                        ],
                    },
                )
            )
            rows = await session.execute(
                select(
                    ObsidianEdgeORM.target_note_id,
                    ObsidianEdgeORM.relation,
                    ObsidianEdgeORM.source_note_id,
                )
            )
        finally:
            await session.close()
            await database.shutdown()
        return (
            [(target or "", relation, source) for target, relation, source in rows],
            current.relative_path,
        )

    related, current_path = anyio.run(scenario)

    assert current_path == "Alexandria/Contexts/Projects/Graph Current.md"
    assert related[0] == ("alexandria_start_here", "cites", "ctx_graph_current")


def test_reindex_resolves_relative_wikilinks_from_source_folder(
    tmp_path: Path,
) -> None:
    """Relative wikilinks should resolve against the source note folder."""

    async def scenario() -> list[tuple[str, str]]:
        database, session, obsidian = await _services(tmp_path)
        root = tmp_path / "vault" / "Alexandria"
        source_path = root / "A Source.md"
        target_path = root / "Z Target.md"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "---\n"
            "alexandria_type: context\n"
            "id: ctx_a_source\n"
            "title: Source\n"
            "status: active\n"
            "---\n"
            "# Source\n\nSee [[Z Target]].\n",
            encoding="utf-8",
        )
        target_path.write_text(
            "---\n"
            "alexandria_type: context\n"
            "id: ctx_z_target\n"
            "title: Target\n"
            "status: active\n"
            "---\n"
            "# Target\n",
            encoding="utf-8",
        )
        try:
            await obsidian.reindex()
            rows = await session.execute(
                select(ObsidianEdgeORM.target_path, ObsidianEdgeORM.target_note_id)
            )
            indexed_edges = [(path, note_id or "") for path, note_id in rows.all()]
        finally:
            await session.close()
            await database.shutdown()
        return indexed_edges

    indexed_edges = anyio.run(scenario)

    assert indexed_edges == [("Alexandria/Z Target.md", "ctx_z_target")]


def test_repository_resolves_edges_after_target_note_is_indexed_later(
    tmp_path: Path,
) -> None:
    """A second resolve pass should fill target ids for late-indexed notes."""

    async def scenario() -> tuple[int, list[tuple[str, str]]]:
        database, session, obsidian = await _services(tmp_path)
        repository = SqlAlchemyObsidianIndexRepository(session=session)
        try:
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Late Source",
                    body="# Late Source\n\nSee [[Late Target]].",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_late_source",
                    relative_path="Alexandria/Late Source.md",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Late Target",
                    body="# Late Target\n",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_late_target",
                    relative_path="Alexandria/Late Target.md",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            resolved = await repository.resolve_edge_targets()
            rows = await session.execute(
                select(ObsidianEdgeORM.target_path, ObsidianEdgeORM.target_note_id)
            )
            edges = [(path, note_id or "") for path, note_id in rows.all()]
        finally:
            await session.close()
            await database.shutdown()
        return resolved, edges

    resolved, edges = anyio.run(scenario)

    assert resolved == 1
    assert edges == [("Alexandria/Late Target.md", "ctx_late_target")]


def test_postgres_edge_source_cache_preserves_incoming_backlink_source(
    tmp_path: Path,
) -> None:
    """PostgreSQL should preserve backlink source rows without serving traversal."""

    async def scenario() -> list[tuple[str, str]]:
        database, session, obsidian = await _services(tmp_path)
        try:
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Target",
                    body="# Target\n\nDestination.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_target",
                    relative_path="Alexandria/Target.md",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Source",
                    body="# Source\n\nSee [[Target]].",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_source",
                    relative_path="Alexandria/Source.md",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            rows = await session.execute(
                select(
                    ObsidianEdgeORM.source_note_id,
                    ObsidianEdgeORM.target_note_id,
                ).where(ObsidianEdgeORM.target_note_id == "ctx_target")
            )
        finally:
            await session.close()
            await database.shutdown()
        return [(source, target or "") for source, target in rows]

    assert anyio.run(scenario) == [("ctx_source", "ctx_target")]


def test_postgres_edge_source_cache_persists_and_replaces_stale_source_edges(
    tmp_path: Path,
) -> None:
    """Saved edge rows should survive reopen and disappear after source replacement."""

    async def scenario() -> tuple[list[str], list[str]]:
        database, session, obsidian = await _services(tmp_path)
        reopened: AsyncSession | None = None
        try:
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Persistent Target",
                    body="# Persistent Target\n",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_persistent_target",
                    relative_path="Alexandria/Persistent Target.md",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Persistent Source",
                    body="# Persistent Source\n\nSee [[Persistent Target]].",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_persistent_source",
                    relative_path="Alexandria/Persistent Source.md",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            await session.commit()
            await session.close()

            reopened = database.session()
            persisted_rows = await reopened.scalars(
                select(ObsidianEdgeORM.edge_id).where(
                    ObsidianEdgeORM.source_note_id == "ctx_persistent_source"
                )
            )
            persisted = list(persisted_rows.all())
            repository = SqlAlchemyObsidianIndexRepository(session=reopened)
            reopened_obsidian = ObsidianService(
                repository=repository,
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
            )
            await reopened_obsidian.save_note(
                ObsidianSaveNote(
                    title="Persistent Source",
                    body="# Persistent Source\n\nRelationship removed.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_persistent_source",
                    relative_path="Alexandria/Persistent Source.md",
                    frontmatter={"scope": "GLOBAL"},
                )
            )
            await reopened.commit()
            remaining_rows = await reopened.scalars(
                select(ObsidianEdgeORM.edge_id).where(
                    ObsidianEdgeORM.source_note_id == "ctx_persistent_source"
                )
            )
            remaining = list(remaining_rows.all())
        finally:
            await session.close()
            if reopened is not None:
                await reopened.close()
            await database.shutdown()
        return persisted, remaining

    persisted, remaining = anyio.run(scenario)

    assert len(persisted) == 1
    assert remaining == []
