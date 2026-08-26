"""Canonical metadata save, index, search, and reindex integration tests."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
from sqlalchemy import select

from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianSearchQuery,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.native_context_reindex_manifest import (
    create_native_context_reindex_manifest_validator,
)
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.models.obsidian_index_models import ObsidianFileORM
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.obsidian.interface.schemas.obsidian.obsidian_schema import (
    ObsidianNoteResponse,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def test_dogfood_metadata_round_trips_through_markdown_index_and_search(
    tmp_path: Path,
) -> None:
    """Typed metadata should survive canonical save, search, and full reindex."""

    async def scenario() -> tuple[str, dict[str, object], dict[str, object], int, int]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        service = ObsidianService(
            repository=SqlAlchemyObsidianIndexRepository(session=session),
            vault_path=str(tmp_path / "vault"),
            alexandria_root="Alexandria",
            context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
        )
        try:
            saved = await service.save_note(
                ObsidianSaveNote(
                    title="Dogfood Metadata Round Trip",
                    body=(
                        "# Dogfood Metadata Round Trip\n\n"
                        "https://example.com/news/2026/07/29/article-123\n"
                        "https://example.com/article?id=12345\n"
                        "https://example.com/article?id=12345"
                        "&access_token=SECRET\n"
                    ),
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="dogfood_metadata_round_trip",
                    project="Evidence Intelligence",
                    tags=(
                        "Evidence Intelligence",
                        "Closing Review v3",
                        "Market",
                        "KRX",
                        "2026-07-29",
                    ),
                    frontmatter={
                        "scope": "PROJECT",
                        "report": "Closing Review v3",
                        "date": "2026-07-29",
                        "source_of_truth": True,
                        "evidence_refs": ("E-MKT-001", "E-MKT-002"),
                        "artifact_refs": (),
                    },
                )
            )
            raw_path = tmp_path / "vault" / saved.relative_path
            raw_markdown = raw_path.read_text(encoding="utf-8")
            indexed = await session.scalar(
                select(ObsidianFileORM).where(ObsidianFileORM.note_id == saved.note_id)
            )
            assert indexed is not None
            indexed_metadata = dict(indexed.frontmatter_json)

            tag_hits = await service.search(
                ObsidianSearchQuery(
                    query="Dogfood Metadata Round Trip",
                    project="Evidence Intelligence",
                    tags=("Evidence Intelligence", "2026-07-29"),
                ),
                refresh=False,
            )
            project_hits = await service.search(
                ObsidianSearchQuery(
                    query="Dogfood Metadata Round Trip",
                    project="Evidence Intelligence",
                ),
                refresh=False,
            )

            await service.reindex()
            read_back = await service.read_note(saved.note_id)
            response_metadata = ObsidianNoteResponse.from_entity(
                read_back
            ).model_dump()["frontmatter"]
            return (
                raw_markdown,
                indexed_metadata,
                response_metadata,
                len(tag_hits),
                len(project_hits),
            )
        finally:
            await session.close()
            await database.shutdown()

    raw, indexed, response, tag_hit_count, project_hit_count = anyio.run(scenario)

    assert "tags:\n  - Evidence Intelligence" in raw
    assert "\ntags: '(" not in raw
    assert "\nsource_of_truth: true\n" in raw
    assert "evidence_refs:\n  - E-MKT-001\n  - E-MKT-002" in raw
    assert "artifact_refs: []" in raw
    assert "https://example.com/news/2026/07/29/article-123" in raw
    assert "https://example.com/article?id=12345\n" in raw
    assert "https://example.com/article?id=12345&access_token=<REDACTED>" in raw

    for metadata in (indexed, response):
        assert metadata["source_of_truth"] is True
        assert metadata["evidence_refs"] == ["E-MKT-001", "E-MKT-002"]
        assert metadata["artifact_refs"] == []
        assert metadata["tags"] == [
            "Evidence Intelligence",
            "Closing Review v3",
            "Market",
            "KRX",
            "2026-07-29",
        ]
    assert tag_hit_count == 1
    assert project_hit_count == 1
