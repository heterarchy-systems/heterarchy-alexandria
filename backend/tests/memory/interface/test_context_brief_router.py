"""Router and MCP gateway tests for the budgeted Context brief."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.memory.context_seed import seed_context

from app.main import app
from app.mcp_server.backend_api_client import (
    AlexandriaApiClient,
    AlexandriaApiError,
    AlexandriaApiSettings,
)
from app.mcp_server.tools.contexts.context_backend_gateway import (
    alexandria_context_brief,
)
from app.memory.domain.event_enum.context_enums import ContextKind, ContextScope
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextBriefRequest,
)
from app.shared.infrastructure.database import Database

_BRIEF_CONTENT = (
    "# Handoff brief seed\n"
    "\n"
    "## Goal\n"
    "Deliver the budgeted context brief end to end.\n"
    "\n"
    "## Constraints\n"
    "Stay within the delivery byte budget.\n"
    "\n"
    "## Next Actions\n"
    "Run the brief router verification.\n"
)


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


async def _seed_brief_contexts() -> list[tuple[str, str]]:
    """Seed two recallable contexts and return (id, title) pairs.

    Returns:
        Seeded context identities.
    """
    async with _database_session() as session:
        seeded: list[tuple[str, str]] = []
        for title in ("Brief seed alpha", "Brief seed beta"):
            record = await seed_context(
                session,
                kind=ContextKind.HANDOFF,
                title=title,
                content=_BRIEF_CONTENT,
                summary="Budgeted brief seed context.",
                project="brief-route",
            )
            seeded.append((record.id, title))
        await session.commit()
        return seeded


def test_brief_route_delivers_budgeted_entries_with_repetition_suppression(
    tmp_path: Path,
) -> None:
    """The brief route must honor budgets and suppress repeated deliveries."""
    del tmp_path
    anyio.run(_seed_brief_contexts)

    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.post(
            "/memory/contexts/retrieval/brief",
            json={
                "query": "budgeted brief",
                "limit": 5,
                "project": "brief-route",
                "include_scopes": ["PROJECT"],
            },
        )
        assert first.status_code == 200, first.text
        first_payload = first.json()

        assert first_payload["entries"], "expected delivered brief entries"
        assert first_payload["total_bytes"] == len(
            first_payload["context_brief"].encode("utf-8")
        )
        assert first_payload["total_bytes"] <= first_payload["byte_budget"]
        assert first_payload["query"] == "budgeted brief"

        previously_delivered = [
            (entry["context_id"], entry["content_hash"])
            for entry in first_payload["entries"]
        ]
        second = client.post(
            "/memory/contexts/retrieval/brief",
            json={
                "query": "budgeted brief",
                "limit": 5,
                "project": "brief-route",
                "include_scopes": ["PROJECT"],
                "previously_delivered": [list(pair) for pair in previously_delivered],
            },
        )
        assert second.status_code == 200, second.text
        second_payload = second.json()

        assert second_payload["entries"] == []
        assert {
            (marker["context_id"], marker["content_hash"])
            for marker in second_payload["already_delivered"]
        } == set(previously_delivered)

        changed = client.post(
            "/memory/contexts/retrieval/brief",
            json={
                "query": "budgeted brief",
                "limit": 5,
                "project": "brief-route",
                "include_scopes": ["PROJECT"],
                "previously_delivered": [
                    [previously_delivered[0][0], "stale" + "0" * 60]
                ],
            },
        )
        assert changed.status_code == 200, changed.text
        changed_payload = changed.json()

        changed_entries = [
            entry
            for entry in changed_payload["entries"]
            if entry["context_id"] == previously_delivered[0][0]
        ]
        assert changed_entries
        assert changed_entries[0]["delivery_status"] == "changed"


def test_tiny_budget_fails_typed_instead_of_empty_success(tmp_path: Path) -> None:
    """A budget that cannot deliver one entry must map to a typed 422."""
    del tmp_path
    anyio.run(_seed_brief_contexts)

    with TestClient(app, raise_server_exceptions=False) as client:
        tiny = client.post(
            "/memory/contexts/retrieval/brief",
            json={
                "query": "budgeted brief",
                "limit": 5,
                "project": "brief-route",
                "include_scopes": ["PROJECT"],
                "byte_budget": 32,
            },
        )

    assert tiny.status_code == 422


def test_brief_reads_do_not_grow_the_change_log(tmp_path: Path) -> None:
    """Brief reads are read-only: the durable change log must not grow."""
    del tmp_path
    anyio.run(_seed_brief_contexts)

    with TestClient(app, raise_server_exceptions=False) as client:
        before = client.get("/memory/contexts/retrieval/changes").json()
        for _ in range(2):
            brief = client.post(
                "/memory/contexts/retrieval/brief",
                json={
                    "query": "budgeted brief",
                    "limit": 5,
                    "project": "brief-route",
                    "include_scopes": ["PROJECT"],
                },
            )
            assert brief.status_code == 200
        after = client.get("/memory/contexts/retrieval/changes").json()

    assert before["entries"] == after["entries"]


def test_mcp_brief_tool_round_trip_through_the_backend_api(tmp_path: Path) -> None:
    """The MCP gateway function must reach the real route via HTTP."""
    del tmp_path
    anyio.run(_mcp_round_trip)


async def _mcp_round_trip() -> None:
    """Run the MCP gateway function against the ASGI app."""
    await _seed_brief_contexts()

    transport = httpx.ASGITransport(app=app)
    client = AlexandriaApiClient(
        AlexandriaApiSettings(base_url="http://testserver"),
        transport=transport,
    )
    payload = await alexandria_context_brief(
        client,
        ContextBriefRequest(
            query="budgeted brief",
            limit=5,
            project="brief-route",
            include_scopes=[ContextScope.PROJECT],
        ),
    )

    assert payload["entries"], "expected delivered brief entries from MCP tool"
    assert payload["query"] == "budgeted brief"

    with pytest.raises(AlexandriaApiError) as excinfo:
        await alexandria_context_brief(
            client,
            ContextBriefRequest(
                query="budgeted brief",
                limit=5,
                project="brief-route",
                include_scopes=[ContextScope.PROJECT],
                byte_budget=32,
            ),
        )
    assert excinfo.value.status_code == 422
