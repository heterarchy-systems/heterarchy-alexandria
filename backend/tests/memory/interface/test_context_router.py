"""Router contract tests for Context Vault endpoints."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import anyio
from app.main import app
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextScope,
    ContextSourceType,
)
from app.memory.infrastructure.models.context_models import (
    ContextAccessEventORM,
    ContextChunkORM,
    ContextORM,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.infrastructure.database import Database
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.memory.context_seed import seed_context


def _context_payload() -> dict[str, object]:
    return {
        "kind": "HANDOFF",
        "title": "API handoff",
        "summary": "API saves and recalls context.",
        "content": """# API handoff

## Summary
API saves and recalls context.

## Current State
- Context API is under test.

## Next Actions
1. Add CLI.

## Restore Prompt
Continue from the API context.
""",
        "project": "heterarchy-alexandria",
        "source_agent": "Hermes",
        "tags": ["api", "handoff"],
    }


@asynccontextmanager
async def _database_session() -> AsyncIterator[AsyncSession]:
    """Yield one PostgreSQL session fully contained in one event loop."""
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    try:
        async with database.session() as session:
            yield session
    finally:
        await database.shutdown()


async def _seed_api_context(
    session: AsyncSession,
    title: str = "API handoff",
    summary: str = "API saves and recalls context.",
    content: str | None = None,
    project: str | None = "heterarchy-alexandria",
    scope: ContextScope = ContextScope.PROJECT,
    user_id: str | None = None,
    source_type: ContextSourceType = ContextSourceType.AGENT,
    restore_prompt: str | None = "Continue from the API context.",
) -> str:
    payload = _context_payload()
    context = await seed_context(
        session,
        kind=ContextKind.HANDOFF,
        title=title,
        summary=summary,
        content=str(payload["content"]) if content is None else content,
        project=project,
        scope=scope,
        user_id=user_id,
        source_agent="Hermes",
        source_type=source_type,
        tags=["api", "handoff"],
        restore_prompt=restore_prompt,
    )
    await session.commit()
    return context.id


async def _set_context_dates(
    session: AsyncSession,
    context_id: str,
    created_at: datetime,
    updated_at: datetime,
) -> None:
    model = await session.get(ContextORM, context_id)
    assert model is not None
    model.created_at = created_at
    model.updated_at = updated_at
    await session.commit()


async def _context_persistence_counts(
    session: AsyncSession,
    context_id: str,
) -> dict[str, int]:
    context_count = await session.scalar(
        select(func.count()).select_from(ContextORM).where(ContextORM.id == context_id)
    )
    chunk_count = await session.scalar(
        select(func.count())
        .select_from(ContextChunkORM)
        .where(ContextChunkORM.context_id == context_id)
    )
    access_event_count = await session.scalar(
        select(func.count())
        .select_from(ContextAccessEventORM)
        .where(ContextAccessEventORM.context_id == context_id)
    )
    return {
        "contexts": int(context_count or 0),
        "chunks": int(chunk_count or 0),
        "access_events": int(access_event_count or 0),
    }


def test_context_api_filters_list_by_created_and_updated_dates(tmp_path: Path) -> None:
    """Context list route should accept created/updated date-range filters."""

    async def seed_date_ranges() -> tuple[str, str, str]:
        database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
        await database.initialize()
        try:
            async with database.session() as session:
                older_id = await _seed_api_context(session, "Older API handoff")
                inside_id = await _seed_api_context(session, "Inside API handoff")
                newer_id = await _seed_api_context(session, "Newer API handoff")
                await _set_context_dates(
                    session,
                    older_id,
                    datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
                    datetime(2026, 5, 17, 11, 0, tzinfo=UTC),
                )
                await _set_context_dates(
                    session,
                    inside_id,
                    datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
                    datetime(2026, 5, 18, 11, 0, tzinfo=UTC),
                )
                await _set_context_dates(
                    session,
                    newer_id,
                    datetime(2026, 5, 19, 10, 0, tzinfo=UTC),
                    datetime(2026, 5, 19, 11, 0, tzinfo=UTC),
                )
                return older_id, inside_id, newer_id
        finally:
            await database.shutdown()

    _older_id, inside_id, _newer_id = anyio.run(seed_date_ranges)
    with TestClient(app, raise_server_exceptions=False) as client:
        created_response = client.get(
            "/memory/contexts",
            params={
                "created_after": "2026-05-18T00:00:00.000Z",
                "created_before": "2026-05-18T23:59:59.999Z",
            },
        )
        updated_response = client.get(
            "/memory/contexts",
            params={
                "updated_after": "2026-05-18T00:00:00.000Z",
                "updated_before": "2026-05-18T23:59:59.999Z",
            },
        )
        naive_response = client.get(
            "/memory/contexts",
            params={"created_after": "2026-05-18T00:00:00"},
        )

    assert created_response.status_code == 200
    assert [item["id"] for item in created_response.json()["items"]] == [inside_id]
    assert updated_response.status_code == 200
    assert [item["id"] for item in updated_response.json()["items"]] == [inside_id]
    assert naive_response.status_code == 422


def test_context_api_hard_deletes_context_rows_chunks_access_events_and_search_index(
    tmp_path: Path,
) -> None:
    """Context delete should remove durable rows and retrieval traces."""

    async def seed_context() -> str:
        async with _database_session() as session:
            return await _seed_api_context(session)

    async def read_counts(context_id: str) -> dict[str, int]:
        async with _database_session() as session:
            return await _context_persistence_counts(session, context_id)

    context_id = anyio.run(seed_context)
    with TestClient(app, raise_server_exceptions=False) as client:
        access_response = client.post(f"/memory/contexts/{context_id}/access")
        before_search_response = client.post(
            "/memory/contexts/retrieval/search",
            json={
                "query": "API saves recalls",
                "strategy": "HYBRID",
                "project": "heterarchy-alexandria",
            },
        )
        delete_response = client.delete(f"/memory/contexts/{context_id}")
        after_get_response = client.get(f"/memory/contexts/{context_id}")
        after_list_response = client.get(
            "/memory/contexts", params={"include_archived": "true"}
        )
        after_search_response = client.post(
            "/memory/contexts/retrieval/search",
            json={
                "query": "API saves recalls",
                "strategy": "HYBRID",
                "project": "heterarchy-alexandria",
            },
        )
    counts = anyio.run(read_counts, context_id)

    assert access_response.status_code == 200
    assert before_search_response.status_code == 200
    assert context_id in before_search_response.json()["context_pack"]
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert after_get_response.status_code == 404
    assert after_list_response.status_code == 200
    assert after_list_response.json()["total"] == 0
    assert after_search_response.status_code == 200
    assert after_search_response.json()["matches"] == []
    assert counts == {"contexts": 0, "chunks": 0, "access_events": 0}


def test_context_api_lists_searches_accesses_and_archives_seeded_context(
    tmp_path: Path,
) -> None:
    """Context API should expose the archive-first recall lifecycle for indexed rows."""

    async def seed_context() -> str:
        async with _database_session() as session:
            return await _seed_api_context(session)

    context_id = anyio.run(seed_context)
    with TestClient(app, raise_server_exceptions=False) as client:
        list_response = client.get(
            "/memory/contexts", params={"project": "heterarchy-alexandria"}
        )
        get_response = client.get(f"/memory/contexts/{context_id}")
        chunks_response = client.get(f"/memory/contexts/{context_id}/chunks")
        search_response = client.post(
            "/memory/contexts/retrieval/search",
            json={
                "query": "API saves recalls",
                "strategy": "HYBRID",
                "project": "heterarchy-alexandria",
            },
        )
        access_response = client.post(f"/memory/contexts/{context_id}/access")
        access_event_response = client.post(
            f"/memory/contexts/{context_id}/access-events",
            json={
                "actor_name": "Alexandria UI",
                "actor_type": "UI",
                "access_method": "DETAIL_VIEW",
                "source_surface": "context-detail",
            },
        )
        access_events_response = client.get(
            f"/memory/contexts/{context_id}/access-events",
            params={"limit": 5},
        )
        archive_response = client.post(f"/memory/contexts/{context_id}/archive")
        rag_response = client.get("/memory/contexts/rag/status")
        reindex_response = client.post("/memory/contexts/retrieval/reindex")

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert get_response.status_code == 200
    assert get_response.json()["id"] == context_id
    assert get_response.json()["restore_prompt"] == "Continue from the API context."
    assert get_response.json()["source_type"] == "AGENT"
    assert get_response.json()["provenance"] == {
        "source_actor_id": "Hermes",
        "source_actor_type": "AGENT",
        "source_run_id": None,
        "external_run_id": None,
        "artifact_refs": [],
        "evidence_refs": [],
        "confidence": None,
    }
    assert get_response.json()["lifecycle"] == {
        "status": "SAVED",
        "content_hash": None,
        "version": None,
        "supersedes_context_id": None,
        "superseded_by_context_id": None,
    }
    assert chunks_response.status_code == 200
    assert chunks_response.json()[0]["context_id"] == context_id
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert search_payload["effective_strategy"] == "FTS_ONLY"
    assert context_id in search_payload["context_pack"]
    assert "vector_score" in search_payload["matches"][0]
    assert search_payload["matches"][0]["vector_score"] is None
    assert "workspace_id" in search_payload["matches"][0]["context"]
    assert search_payload["matches"][0]["context"]["workspace_id"] is None
    assert "graph_evidence" not in search_payload["matches"][0]
    assert access_response.status_code == 200
    assert access_response.json()["access_count"] == 1
    assert access_event_response.status_code == 404
    assert access_events_response.status_code == 404
    assert archive_response.status_code == 200
    assert archive_response.json()["is_archived"] is True
    assert rag_response.status_code == 200
    assert rag_response.json()["fts"] == "HEALTHY"
    assert rag_response.headers["X-Alexandria-Retrieval-Kernel-Authority"] == "test"
    assert reindex_response.status_code == 409
    assert reindex_response.json()["detail"]["error_code"] == (
        "EMBEDDING_REINDEX_REQUIRES_QUEUE"
    )
    assert reindex_response.json()["detail"]["submission_endpoint"] == (
        "/operations/maintenance/embedding-reindex/jobs"
    )


def test_context_api_gets_and_archives_source_qualified_obsidian_context(
    tmp_path: Path,
) -> None:
    """Existing Context routes must operate on canonical Obsidian search IDs."""
    del tmp_path

    async def seed_note() -> None:
        async with _database_session() as session:
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=os.environ["SERVICE_OBSIDIAN_VAULT_PATH"],
                alexandria_root=os.environ["SERVICE_ALEXANDRIA_OBSIDIAN_ROOT"],
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Router Canonical Context",
                    body="# Canonical\n\nrouter canonical context",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_router_canonical",
                    status="current",
                    project="heterarchy-alexandria",
                    frontmatter={
                        "scope": "PROJECT",
                        "provenance": {
                            "source_actor_id": "hermes-coding",
                            "source_actor_type": "AGENT",
                            "source_run_id": "platform-run-001",
                            "external_run_id": "external-run-001",
                            "artifact_refs": ["artifact://test-results.json"],
                            "evidence_refs": ["context://decision-001"],
                            "confidence": "HIGH",
                        },
                    },
                )
            )
            await session.commit()

    async def read_note_status() -> str:
        async with _database_session() as session:
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=os.environ["SERVICE_OBSIDIAN_VAULT_PATH"],
                alexandria_root=os.environ["SERVICE_ALEXANDRIA_OBSIDIAN_ROOT"],
            )
            note = await obsidian_service.read_note("ctx_router_canonical")
            return note.status

    anyio.run(seed_note)
    with TestClient(app, raise_server_exceptions=False) as client:
        get_response = client.get("/memory/contexts/obsidian:ctx_router_canonical")
        archive_response = client.post(
            "/memory/contexts/obsidian:ctx_router_canonical/archive"
        )
    canonical_status = anyio.run(read_note_status)

    assert get_response.status_code == 200
    assert get_response.json()["id"] == "obsidian:ctx_router_canonical"
    assert get_response.json()["canonical_context_id"] == "ctx_router_canonical"
    assert get_response.json()["lifecycle_status"] == "CURRENT"
    assert get_response.json()["provenance"] == {
        "source_actor_id": "hermes-coding",
        "source_actor_type": "AGENT",
        "source_run_id": "platform-run-001",
        "external_run_id": "external-run-001",
        "artifact_refs": ["artifact://test-results.json"],
        "evidence_refs": ["context://decision-001"],
        "confidence": "HIGH",
    }
    assert get_response.json()["lifecycle"]["status"] == "CURRENT"
    assert len(get_response.json()["lifecycle"]["content_hash"]) == 64
    assert get_response.json()["lifecycle"]["version"] == 1
    assert archive_response.status_code == 200
    assert archive_response.json()["lifecycle_status"] == "ARCHIVED"
    assert archive_response.json()["lifecycle"]["status"] == "ARCHIVED"
    assert archive_response.json()["is_archived"] is True
    assert canonical_status == "archived"


def test_context_api_supersedes_existing_canonical_contexts(tmp_path: Path) -> None:
    """Context API must expose idempotent bidirectional canonical supersede."""
    del tmp_path

    async def seed_notes() -> None:
        async with _database_session() as session:
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=os.environ["SERVICE_OBSIDIAN_VAULT_PATH"],
                alexandria_root=os.environ["SERVICE_ALEXANDRIA_OBSIDIAN_ROOT"],
            )
            for note_id, title, body in (
                ("ctx_api_old", "API Old", "# Old\n\nold body remains"),
                ("ctx_api_new", "API New", "# New\n\nnew body remains"),
            ):
                await obsidian_service.save_note(
                    ObsidianSaveNote(
                        title=title,
                        body=body,
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        note_id=note_id,
                        status="current",
                        project="heterarchy-alexandria",
                        frontmatter={"scope": "PROJECT"},
                    )
                )
            await session.commit()

    async def read_note_body(note_id: str) -> str:
        async with _database_session() as session:
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=os.environ["SERVICE_OBSIDIAN_VAULT_PATH"],
                alexandria_root=os.environ["SERVICE_ALEXANDRIA_OBSIDIAN_ROOT"],
            )
            note = await obsidian_service.read_note(note_id)
            return note.body

    anyio.run(seed_notes)
    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.post(
            "/memory/contexts/obsidian:ctx_api_old/supersede",
            json={"replacement_context_id": "obsidian:ctx_api_new"},
        )
        retry = client.post(
            "/memory/contexts/obsidian:ctx_api_old/supersede",
            json={"replacement_context_id": "obsidian:ctx_api_new"},
        )
        self_response = client.post(
            "/memory/contexts/obsidian:ctx_api_old/supersede",
            json={"replacement_context_id": "obsidian:ctx_api_old"},
        )
        missing = client.post(
            "/memory/contexts/obsidian:ctx_api_old/supersede",
            json={"replacement_context_id": "obsidian:ctx_missing"},
        )
        sql_id = client.post(
            "/memory/contexts/sql-context/supersede",
            json={"replacement_context_id": "obsidian:ctx_api_new"},
        )
    old_body = anyio.run(read_note_body, "ctx_api_old")
    new_body = anyio.run(read_note_body, "ctx_api_new")

    assert first.status_code == 200
    payload = first.json()
    assert payload["superseded"]["lifecycle_status"] == "SUPERSEDED"
    assert (
        payload["superseded"]["lifecycle"]["superseded_by_context_id"] == "ctx_api_new"
    )
    assert payload["replacement"]["lifecycle_status"] == "CURRENT"
    assert payload["replacement"]["lifecycle"]["supersedes_context_id"] == "ctx_api_old"
    assert retry.status_code == 200
    assert retry.json()["superseded"]["lifecycle"]["version"] == 2
    assert retry.json()["replacement"]["lifecycle"]["version"] == 2
    assert self_response.status_code == 400
    assert "INVALID_SUPERSEDE" in self_response.text
    assert missing.status_code == 404
    assert sql_id.status_code == 400
    assert "old body remains" in old_body
    assert "new body remains" in new_body


def test_context_api_filters_recall_by_memory_scope(tmp_path: Path) -> None:
    """Scoped recall should return only contexts from requested memory lanes."""

    async def seed_scopes() -> str:
        scoped_content = "# Scoped recall\n\n## Summary\nScoped recall token."
        async with _database_session() as session:
            await _seed_api_context(
                session,
                "Project scoped recall",
                "Scoped recall token.",
                scoped_content,
                "heterarchy-alexandria",
                ContextScope.PROJECT,
            )
            return await _seed_api_context(
                session,
                "User scoped recall",
                "Scoped recall token.",
                scoped_content,
                "heterarchy-alexandria",
                ContextScope.USER,
                "ha_nori",
            )

    user_context_id = anyio.run(seed_scopes)
    with TestClient(app, raise_server_exceptions=False) as client:
        search_response = client.post(
            "/memory/contexts/retrieval/search",
            json={
                "query": "Scoped recall token",
                "include_scopes": ["USER"],
                "user_id": "ha_nori",
            },
        )

    assert search_response.status_code == 200
    matches = search_response.json()["matches"]
    assert {match["context"]["id"] for match in matches} == {user_context_id}
    assert search_response.json()["recall_scopes"] == ["USER"]


def test_context_api_rejects_missing_scope_identity_with_422(tmp_path: Path) -> None:
    """Requested scope lanes should require their identity at the HTTP boundary."""
    del tmp_path
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/memory/contexts/retrieval/search",
            json={
                "query": "Scoped recall token",
                "include_scopes": ["AGENT"],
            },
        )

    assert response.status_code == 422
    assert "MISSING_AGENT_ID" in response.text


def test_context_api_write_routes_are_not_exposed() -> None:
    """Context Vault capture and compact-save routes should be absent."""
    with TestClient(app, raise_server_exceptions=False) as client:
        capture_response = client.post(
            "/memory/contexts/capture", json=_context_payload()
        )
        compact_response = client.post(
            "/memory/contexts/prepare-compact",
            json={"current_goal": "Context API"},
        )

    assert capture_response.status_code in {404, 405}
    assert compact_response.status_code in {404, 405}


def test_context_access_event_detail_routes_are_not_exposed(
    tmp_path: Path,
) -> None:
    """Detailed context access-event routes should stay internal-only."""
    del tmp_path

    async def seed_context() -> str:
        async with _database_session() as session:
            return await _seed_api_context(session)

    async def read_counts(context_id: str) -> dict[str, int]:
        async with _database_session() as session:
            return await _context_persistence_counts(session, context_id)

    context_id = anyio.run(seed_context)
    with TestClient(app, raise_server_exceptions=False) as client:
        access_response = client.post(f"/memory/contexts/{context_id}/access")
        post_event_response = client.post(
            f"/memory/contexts/{context_id}/access-events",
            json={
                "actor_name": "Alexandria UI",
                "actor_type": "UI",
                "access_method": "DETAIL_VIEW",
                "source_surface": "context-detail",
            },
        )
        get_events_response = client.get(f"/memory/contexts/{context_id}/access-events")
    counts = anyio.run(read_counts, context_id)

    assert access_response.status_code == 200
    assert access_response.json()["access_count"] == 1
    assert post_event_response.status_code == 404
    assert get_events_response.status_code == 404
    assert counts["access_events"] == 1
