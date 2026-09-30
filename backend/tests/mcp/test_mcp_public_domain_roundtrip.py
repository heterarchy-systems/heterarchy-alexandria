"""Real public MCP JSON to FastAPI/domain roundtrip evidence for WP15."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.mcp_server.backend_api_client import AlexandriaApiClient, AlexandriaApiSettings
from app.mcp_server.server_runtime import build_mcp_server
from app.memory.application.reconciliation.cycles.memory_cycle_planning import (
    compact_source_hashes_match,
)
from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)
from app.memory.domain.entities.memory_cycle import MemoryCycleSourceSnapshot
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.infrastructure.models.context_models import ContextORM
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.infrastructure.database import Database


def test_compact_source_refs_are_an_exact_verified_subset_of_cycle_sources() -> None:
    """Selected Compact refs may be a subset, but every ref must bind exactly once."""
    now = datetime(2026, 9, 30, tzinfo=UTC)
    sources = (
        MemoryCycleSourceSnapshot(
            context_id="sql:context",
            canonical_path="context:context",
            content_hash="a" * 64,
            source_revision="sql-revision",
        ),
        MemoryCycleSourceSnapshot(
            context_id="obsidian:note",
            canonical_path="Alexandria/note.md",
            content_hash="b" * 64,
            source_revision="obsidian-revision",
        ),
    )

    def compact(refs: tuple[MemoryCompactSourceRef, ...]) -> MemoryCompact:
        return MemoryCompact(
            id="compact-1",
            project="project",
            covered_from=now,
            covered_to=now,
            markdown_body="# Compact",
            status=MemoryCompactStatus.DRAFT,
            source_refs=refs,
            created_at=now,
            updated_at=now,
            archived_at=None,
        )

    selected = (
        MemoryCompactSourceRef(
            id="ref-1",
            compact_id="compact-1",
            source_type="AGENT",
            source_id="sql:context",
            title="Context",
            detail_path="context:context",
            source_hash="a" * 64,
        ),
    )
    assert compact_source_hashes_match(compact(selected), sources)
    assert not compact_source_hashes_match(
        compact(
            (
                *selected,
                MemoryCompactSourceRef(
                    id="ref-2",
                    compact_id="compact-1",
                    source_type="AGENT",
                    source_id="extra",
                    title="Extra",
                    detail_path="extra",
                    source_hash="c" * 64,
                ),
            )
        ),
        sources,
    )
    assert not compact_source_hashes_match(compact((*selected, selected[0])), sources)
    assert not compact_source_hashes_match(
        compact(
            (
                MemoryCompactSourceRef(
                    id="ref-1",
                    compact_id="compact-1",
                    source_type="AGENT",
                    source_id="sql:context",
                    title="Context",
                    detail_path="context:context",
                    source_hash="d" * 64,
                ),
            )
        ),
        sources,
    )


@asynccontextmanager
async def _database_session() -> AsyncIterator[AsyncSession]:
    """Open one real PostgreSQL session inside the active test loop."""
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    try:
        async with database.session() as session:
            yield session
    finally:
        await database.shutdown()


def _client() -> AlexandriaApiClient:
    """Build the native MCP HTTP client over the real FastAPI app."""
    return AlexandriaApiClient(
        AlexandriaApiSettings(base_url="http://testserver"),
        transport=httpx.ASGITransport(app=app),
    )


async def _run_tool(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Run one registered MCP tool with raw JSON arguments."""
    tool = server._tool_manager.get_tool(name)
    assert tool is not None, name
    return await tool.run(dict(arguments), None, convert_result=True)


async def _with_lifespan(scenario: Any) -> Any:
    """Run one roundtrip while owning the production app resource lifespan."""
    async with app.router.lifespan_context(app):
        return await scenario()


def _payload(result: Any) -> dict[str, Any]:
    """Extract the declared JSON object from one successful MCP result."""
    assert not result.is_error, result.content
    structured = result.structured_content
    assert isinstance(structured, dict)
    nested = structured.get("result")
    return nested if isinstance(nested, dict) else structured


def _server() -> Any:
    """Compose registered production tools against the real local API app."""
    return build_mcp_server(client=_client())


def _upsert_request(
    *,
    key: str,
    body: str,
    expected_content_hash: str | None = None,
) -> dict[str, Any]:
    """Build one public JSON verified-upsert request."""
    request: dict[str, Any] = {
        "identity": {
            "project": "wp15-public-roundtrip",
            "report": "public-boundary",
            "date": "2026-09-30",
            "entity": "mcp",
        },
        "title": "WP15 public boundary",
        "body": body,
        "alexandria_type": "context",
        "idempotency_key": key,
    }
    if expected_content_hash is not None:
        request["expected_content_hash"] = expected_content_hash
    return {"request": request}


def test_registered_verified_upsert_roundtrips_create_replay_update_cas_and_outcome() -> (
    None
):
    """Registered MCP JSON reaches the real write, replay, CAS, and receipt paths."""

    async def scenario() -> None:
        server = _server()
        first = _payload(
            await _run_tool(
                server,
                "alexandria_verified_upsert",
                _upsert_request(key="wp15:create", body="# First body"),
            )
        )
        replay = _payload(
            await _run_tool(
                server,
                "alexandria_verified_upsert",
                _upsert_request(key="wp15:create", body="# First body"),
            )
        )
        assert first["operation"] == "created"
        assert replay["operation"] == "idempotent_replay"
        assert replay["content_hash"] == first["content_hash"]

        updated = _payload(
            await _run_tool(
                server,
                "alexandria_verified_upsert",
                _upsert_request(
                    key="wp15:update",
                    body="# Updated body",
                    expected_content_hash=first["content_hash"],
                ),
            )
        )
        assert updated["operation"] == "updated"
        assert updated["content_hash"] != first["content_hash"]

        with pytest.raises(Exception, match="HTTP 409"):
            await _run_tool(
                server,
                "alexandria_verified_upsert",
                _upsert_request(
                    key="wp15:stale",
                    body="# Stale update",
                    expected_content_hash=first["content_hash"],
                ),
            )

        outcome = _payload(
            await _run_tool(
                server,
                "alexandria_get_mutation_outcome",
                {
                    "request": {
                        "operation": "verified_upsert",
                        "idempotency_key": "wp15:update",
                    }
                },
            )
        )
        assert outcome["status"] == "COMMITTED"
        assert outcome["canonical_path"] == updated["canonical_path"]

    anyio.run(_with_lifespan, scenario)


async def _seed_recall_context() -> None:
    """Seed one real PostgreSQL Context with FTS evidence."""
    from tests.memory.context_seed import seed_context

    from app.memory.domain.event_enum.context_enums import ContextKind

    async with _database_session() as session:
        await seed_context(
            session,
            kind=ContextKind.HANDOFF,
            title="WP15 recall source",
            summary="Real MCP recall source.",
            content="# WP15 recall\\n\\nPublic boundary FTS evidence.",
            project="wp15-recall",
        )
        await session.commit()


def test_registered_recall_exposes_strict_scope_nullable_provenance_and_trace() -> None:
    """Recall JSON traverses the real route and keeps unavailable lanes explicit."""

    async def scenario() -> None:
        await _seed_recall_context()
        server = _server()
        auto = _payload(
            await _run_tool(
                server,
                "alexandria_recall",
                {
                    "request": {
                        "query": "Public boundary FTS evidence",
                        "project": "wp15-recall",
                    }
                },
            )
        )
        strict = _payload(
            await _run_tool(
                server,
                "alexandria_recall",
                {
                    "request": {
                        "query": "Public boundary FTS evidence",
                        "scope_mode": "STRICT",
                        "include_scopes": ["PROJECT"],
                        "project": "wp15-recall",
                    }
                },
            )
        )
        assert auto["matches"]
        assert strict["recall_scopes"] == ["PROJECT"]
        provenance = auto["matches"][0]["provenance"]
        assert provenance.get("vector_score") is None
        assert provenance.get("graph_score") is None
        assert "trace" in auto
        assert isinstance(auto["trace"]["stages"], list)
        assert all(
            {"route", "status", "warnings", "degraded"} <= set(stage)
            for stage in auto["trace"]["stages"]
        )

    anyio.run(_with_lifespan, scenario)


async def _seed_cycle_source(server: Any) -> dict[str, Any]:
    """Create a real Markdown source through the registered upsert tool."""
    source = _payload(
        await _run_tool(
            server,
            "alexandria_verified_upsert",
            {
                "request": {
                    "identity": {
                        "project": "wp15-cycle",
                        "report": "cycle-source",
                        "date": "2026-09-30",
                        "entity": "mcp",
                    },
                    "title": "WP15 cycle source",
                    "body": "# Cycle source\\n\\nCycle source evidence.",
                    "alexandria_type": "context",
                    "idempotency_key": "wp15:cycle:create",
                }
            },
        )
    )
    async with _database_session() as session:
        config = ObsidianVaultConfigStore(
            default_vault_path=app.state.app_config.obsidian_vault_path,
            default_alexandria_root=app.state.app_config.alexandria_obsidian_root,
            config_path=None,
        )
        service = ObsidianService(
            repository=SqlAlchemyObsidianIndexRepository(session=session),
            vault_config_store=config,
            index_maintenance_coordinator=await app.state.container.index_maintenance_coordinator(),
        )
        await service.save_note(
            ObsidianSaveNote(
                note_id=source["note_id"],
                relative_path=source["canonical_path"],
                title="WP15 cycle source",
                body="# Cycle source\n\nCycle source evidence.",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                project="wp15-cycle",
                frontmatter={
                    "scope": "PROJECT",
                    "visibility": "PROJECT",
                    "canonical_claims": json.dumps(
                        [
                            {
                                "subject": "system",
                                "predicate": "authority",
                                "object": "postgresql",
                                "scope": "PROJECT",
                                "project": "wp15-cycle",
                            }
                        ],
                        separators=(",", ":"),
                    ),
                    "evidence_refs": ["source:wp15-cycle"],
                },
            )
        )
        await session.commit()
    from tests.memory.context_seed import seed_context

    from app.memory.domain.event_enum.context_enums import ContextKind

    async with _database_session() as session:
        context = await seed_context(
            session,
            kind=ContextKind.HANDOFF,
            title="WP15 cycle source",
            summary="Cycle source evidence.",
            content="# Cycle source\n\nCycle source evidence.",
            project="wp15-cycle",
            context_metadata={
                "canonical_claims": [
                    {
                        "subject": "system",
                        "predicate": "authority",
                        "object": "postgresql",
                        "scope": "PROJECT",
                        "project": "wp15-cycle",
                    }
                ],
                "evidence_refs": ["source:wp15-cycle"],
            },
        )
        await session.commit()
    return {**source, "context_id": context.id}


def test_registered_memory_cycle_dry_run_apply_replay_hash_and_source_fences() -> None:
    """The registered cycle tool proves plan stability and apply fences over real source."""

    async def scenario() -> None:
        server = _server()
        source = await _seed_cycle_source(server)
        now = datetime.now(UTC)
        base = {
            "project": "wp15-cycle",
            "scope": "PROJECT",
            "window_start": (now - timedelta(days=1)).isoformat(),
            "window_end": (now + timedelta(minutes=1)).isoformat(),
            "idempotency_key": "wp15:cycle",
            "operation": "dry_run",
        }
        first = _payload(
            await _run_tool(server, "alexandria_memory_cycle", {"request": base})
        )
        second = _payload(
            await _run_tool(server, "alexandria_memory_cycle", {"request": base})
        )
        assert first["plan_hash"] == second["plan_hash"]

        apply_request = dict(base)
        apply_request.update(
            operation="apply",
            expected_plan_hash=first["plan_hash"],
        )
        applied = _payload(
            await _run_tool(
                server,
                "alexandria_memory_cycle",
                {"request": apply_request},
            )
        )
        assert applied["status"] in {"APPLIED", "PARTIAL"}
        replayed = _payload(
            await _run_tool(
                server,
                "alexandria_memory_cycle",
                {"request": apply_request},
            )
        )
        assert replayed["replayed"] is True

        wrong_hash = dict(apply_request)
        wrong_hash["expected_plan_hash"] = "f" * 64
        with pytest.raises(Exception, match="HTTP 409"):
            await _run_tool(
                server,
                "alexandria_memory_cycle",
                {"request": wrong_hash},
            )

        async with _database_session() as session:
            await session.execute(
                update(ContextORM)
                .where(ContextORM.id == source["context_id"])
                .values(
                    content="# Drifted SQL cycle source",
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
        with pytest.raises(Exception, match="HTTP 409"):
            await _run_tool(
                server,
                "alexandria_memory_cycle",
                {"request": apply_request},
            )

    anyio.run(_with_lifespan, scenario)


async def _seed_brief_context() -> None:
    """Seed real Context search rows for the registered brief tool."""
    from tests.memory.context_seed import seed_context

    from app.memory.domain.event_enum.context_enums import ContextKind

    async with _database_session() as session:
        await seed_context(
            session,
            kind=ContextKind.HANDOFF,
            title="WP15 brief source",
            summary="Real brief source.",
            content="# WP15 brief\\n\\nBrief source retrieval evidence.",
            project="wp15-brief",
        )
        await session.commit()


def test_registered_context_brief_suppresses_and_refetches_real_source() -> None:
    """The registered brief tool preserves source hashes for suppression/refetch."""

    async def scenario() -> None:
        await _seed_brief_context()
        server = _server()
        request = {
            "query": "Brief source retrieval evidence",
            "project": "wp15-brief",
            "include_scopes": ["PROJECT"],
        }
        first = _payload(await _run_tool(server, "alexandria_context_brief", request))
        assert first["entries"]
        delivered = [
            [entry["context_id"], entry["content_hash"]] for entry in first["entries"]
        ]
        suppressed = _payload(
            await _run_tool(
                server,
                "alexandria_context_brief",
                {**request, "previously_delivered": delivered},
            )
        )
        assert suppressed["entries"] == []
        assert suppressed["already_delivered"]

        async with _database_session() as session:
            context_id = delivered[0][0]
            await session.execute(
                update(ContextORM)
                .where(ContextORM.id == context_id)
                .values(
                    content="Updated source content for refetch.",
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
        refetched = _payload(
            await _run_tool(
                server,
                "alexandria_context_brief",
                {
                    **request,
                    "previously_delivered": [[delivered[0][0], "stale-hash"]],
                },
            )
        )
        assert refetched["entries"]
        assert refetched["entries"][0]["delivery_status"] == "changed"

    anyio.run(_with_lifespan, scenario)


def test_registered_draft_edit_review_apply_binds_final_body_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real source/body journey; only independent RAG health admission is controlled."""
    from tests.memory.interface.test_memory_compact_router import _FakeContextService
    from tests.memory.test_memory_compact_service import _compact_body

    from app.memory.application.contexts.records.context_service import ContextService
    from app.memory.domain.event_enum.context_enums import RagHealthState

    async def admitted_rag_health(_service):
        return await _FakeContextService(
            RagHealthState.HEALTHY
        ).rag_health_with_index_status()

    async def denied_rag_health(_service):
        return await _FakeContextService(
            RagHealthState.DEGRADED
        ).rag_health_with_index_status()

    async def scenario() -> None:
        server = _server()
        source_request = _upsert_request(
            key="wp15:draft-source", body="# Project decision evidence"
        )
        source_request["request"]["identity"]["entity"] = "draft-source"
        source = _payload(
            await _run_tool(server, "alexandria_verified_upsert", source_request)
        )
        body = _compact_body(project="wp15-public-roundtrip").replace(
            "Context source supports", "Project decision evidence supports"
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            created = await http.post(
                "/memory/compacts",
                json={
                    "project": "wp15-public-roundtrip",
                    "covered_from": "2026-05-01T00:00:00Z",
                    "covered_to": "2026-05-10T00:00:00Z",
                    "markdown_body": body,
                    "status": "DRAFT",
                    "source_refs": [
                        {
                            "source_type": "obsidian",
                            "source_id": source["note_id"],
                            "title": "Project decision evidence",
                            "detail_path": source["canonical_path"],
                            "source_hash": source["content_hash"],
                        }
                    ],
                },
            )
        assert created.status_code == 201, created.text
        draft = created.json()
        old_review = _payload(
            await _run_tool(
                server,
                "alexandria_review_memory_compact_draft",
                {"compact_id": draft["id"]},
            )
        )
        edited = _payload(
            await _run_tool(
                server,
                "alexandria_edit_memory_compact_draft",
                {
                    "compact_id": draft["id"],
                    "expected_draft_hash": draft["draft_hash"],
                    "markdown_body": body + "\nProject-specific final decision.\n",
                },
            )
        )
        assert edited["review_receipt_hash"] is None
        monkeypatch.setattr(
            ContextService, "rag_health_with_index_status", denied_rag_health
        )
        with pytest.raises(Exception, match="HTTP 400"):
            await _run_tool(
                server,
                "alexandria_apply_reviewed_memory_compact",
                {
                    "compact_id": draft["id"],
                    "expected_review_hash": old_review["review_hash"],
                },
            )
        monkeypatch.setattr(
            ContextService, "rag_health_with_index_status", admitted_rag_health
        )
        with pytest.raises(Exception, match="HTTP 409"):
            await _run_tool(
                server,
                "alexandria_apply_reviewed_memory_compact",
                {
                    "compact_id": draft["id"],
                    "expected_review_hash": old_review["review_hash"],
                },
            )
        review = _payload(
            await _run_tool(
                server,
                "alexandria_review_memory_compact_draft",
                {"compact_id": draft["id"]},
            )
        )
        assert review["total_score"] == review["max_score"] == 20
        applied = _payload(
            await _run_tool(
                server,
                "alexandria_apply_reviewed_memory_compact",
                {
                    "compact_id": draft["id"],
                    "expected_review_hash": review["review_hash"],
                },
            )
        )
        assert applied["reviewed_body_hash"] == applied["current_body_hash"]
        assert applied["review_receipt_hash"] == review["review_hash"]
        assert applied["review_attestation_status"] == "VERIFIED"
        current = _payload(
            await _run_tool(
                server,
                "alexandria_get_current_memory_compact",
                {"project": "wp15-public-roundtrip"},
            )
        )
        assert current["id"] == draft["id"]
        assert "Project-specific final decision." in current["markdown_body"]

    anyio.run(_with_lifespan, scenario)


def test_registered_recovery_preview_has_real_bounded_capabilities() -> None:
    """Real public dry-run uses composed owners without capability scaffolds."""

    async def scenario():
        server = _server()
        from app.operations.application.recovery.execution.recovery_run_contracts import (
            resolve_recovery_service,
        )
        from app.operations.application.recovery.execution.recovery_run_verification_service import (
            RecoveryRunVerificationService,
        )

        source_request = _upsert_request(
            key="wp15:recovery-source", body="# Recovery representative source"
        )
        source_request["request"]["identity"]["entity"] = "recovery-source"
        source_request["request"]["title"] = "Recovery representative source"
        source = _payload(
            await _run_tool(server, "alexandria_verified_upsert", source_request)
        )
        root = app.state.container
        database = await resolve_recovery_service(root.database)
        async with database.request_session():
            obsidian = await resolve_recovery_service(root.obsidian.obsidian_service)
            context = await resolve_recovery_service(root.memory.context_service)
            graph = await resolve_recovery_service(
                root.obsidian.graph_projection_rebuild_service
            )
            verifier = RecoveryRunVerificationService(
                database=database,
                context_service=context,
                obsidian_service=obsidian,
                graph_projection_service=graph,
            )
            proof = await verifier.verify_representative_search(
                obsidian, source["canonical_path"]
            )
            assert proof["matched"] is True, proof
            assert proof["expected_id"] == source["note_id"]
        arguments = {"dry_run": True, "idempotency_key": "wp15:recovery-preview"}
        first = _payload(await _run_tool(server, "alexandria_recover", arguments))
        repeated = _payload(await _run_tool(server, "alexandria_recover", arguments))
        assert first["plan_hash"] == repeated["plan_hash"]
        assert len(first["plan_hash"]) == 64
        assert not any("unavailable" in reason for reason in first["blocked_reasons"])
        assert first["dry_run"] is True

    anyio.run(_with_lifespan, scenario)
