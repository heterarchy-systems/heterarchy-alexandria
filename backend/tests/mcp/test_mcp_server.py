"""MCP server tests for HTTP-only Alexandria tools."""

from __future__ import annotations

from collections.abc import Awaitable
from inspect import iscoroutinefunction

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app as default_app, create_app
from app.mcp_server.backend_api_client import (
    AlexandriaApiClient,
    AlexandriaApiSettings,
)
from app.mcp_server.server_runtime import (
    DEFAULT_MCP_TRANSPORT_HOST,
    build_mcp_server,
    mcp_transport_security,
)
from app.mcp_server.tools.contexts.context_backend_gateway import (
    alexandria_archive_context,
    alexandria_delete_context,
    alexandria_rag_status,
    alexandria_search,
    alexandria_supersede_context,
)
from app.mcp_server.tools.memory_compacts.memory_compact_tools import (
    alexandria_create_memory_compact,
    alexandria_get_current_memory_compact,
    alexandria_get_memory_compact,
    alexandria_list_memory_compact_artifacts,
    alexandria_review_memory_compact,
)
from app.mcp_server.tools.memory_compacts.memory_steward_readiness_tools import (
    alexandria_memory_steward_readiness,
    alexandria_memory_steward_refresh_current_compact,
)
from app.mcp_server.tools.obsidian.obsidian_backend_gateway import (
    alexandria_check_path_exists,
    alexandria_create_note,
    alexandria_get_related_notes,
    alexandria_read_note,
    alexandria_resolve_canonical_identity,
    alexandria_search_vault,
    alexandria_update_note,
    alexandria_upsert_note,
    alexandria_upsert_report_bundle,
)
from app.mcp_server.tools.obsidian.vault_maintenance_backend_gateway import (
    alexandria_get_graph_build_status,
    alexandria_get_graph_projection_status,
    alexandria_rebuild_graph_projection,
    alexandria_rebuild_note_graph,
    alexandria_reindex_vault,
    alexandria_validate_note_links,
    alexandria_vault_apply_moves,
    alexandria_vault_inventory,
    alexandria_vault_move_plan,
    alexandria_vault_path_search,
    alexandria_vault_review_apply_moves,
    alexandria_vault_review_move_plan,
    alexandria_vault_review_queue,
)
from app.mcp_server.tools.operations.operations_backend_gateway import (
    alexandria_operational_readiness,
    alexandria_recover,
    alexandria_recovery_run_status,
)
from app.mcp_server.tools.skills.skill_backend_gateway import (
    alexandria_search_skills,
    alexandria_skill_acquisition_job_status,
    alexandria_start_skill_acquisition,
)
from app.memory.domain.event_enum.context_enums import (
    ContextRecallLifecycleStatus,
    MemoryFunction,
    RagStrategy,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactStatus,
)
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextSearchRequest,
)
from app.platform.config.app_config import AppConfig
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONValue

RecordedCall = httpx.Request
_ROUTER_PACKAGES = [
    "app.connections.interface.routers",
    "app.librarian.interface.routers",
    "app.memory.interface.routers",
    "app.obsidian.interface.routers",
    "app.operations.interface.routers",
]


def _client() -> tuple[AlexandriaApiClient, list[RecordedCall]]:
    calls: list[RecordedCall] = []

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json({"ok": True}))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )
    return client, calls


def _client_with_payload(
    response_payload: JSONValue,
) -> tuple[AlexandriaApiClient, list[RecordedCall]]:
    calls: list[RecordedCall] = []

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(response_payload))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )
    return client, calls


async def _await_json(awaitable: Awaitable[JSONValue]) -> JSONValue:
    result = await awaitable
    return result


def _run_json(awaitable: Awaitable[JSONValue]) -> JSONValue:
    result = anyio.run(_await_json, awaitable)
    return result


def _compact_review_payload(
    compact_id: str = "compact-1",
    *,
    verdict: str = "pass",
) -> JSONValue:
    return {
        "compact_id": compact_id,
        "verdict": verdict,
        "total_score": 20 if verdict == "pass" else 12,
        "max_score": 20,
        "scores": [],
        "missing_refs": [],
        "contradictions": [],
        "stale_reasons": [],
        "recommended_actions": (
            ["promote_or_keep_current"]
            if verdict == "pass"
            else ["revise_memory_compact"]
        ),
    }


def test_mcp_vault_search_compacts_and_deduplicates_note_hits() -> None:
    """Vault search should return one metadata-only hit per note."""
    client, _ = _client_with_payload(
        {
            "items": [
                {
                    "note": {
                        "id": "note-1",
                        "alexandria_type": "context",
                        "path": "Contexts/Projects/One.md",
                        "title": "One",
                        "status": "active",
                        "tags": ["search"],
                        "project": "heterarchy-alexandria",
                        "content_hash": "a" * 64,
                        "index_status": "indexed",
                        "wikilink": "[[Contexts/Projects/One]]",
                        "body": "full markdown body must not cross the MCP boundary",
                        "frontmatter": {"large": "payload"},
                    },
                    "excerpt": "best matching excerpt",
                    "score": 0.9,
                    "chunk_id": "chunk-1",
                    "heading_path": "Summary",
                },
                {
                    "note": {
                        "id": "note-1",
                        "alexandria_type": "context",
                        "path": "Contexts/Projects/One.md",
                        "title": "One",
                        "status": "active",
                        "tags": ["search"],
                        "project": "heterarchy-alexandria",
                        "content_hash": "a" * 64,
                        "index_status": "indexed",
                    },
                    "excerpt": "lower ranked duplicate chunk",
                    "score": 0.7,
                    "chunk_id": "chunk-2",
                    "heading_path": "Details",
                },
            ],
            "total": 2,
        }
    )

    response = _run_json(alexandria_search_vault(client, query="one", limit=5))

    assert response == {
        "items": [
            {
                "note": {
                    "note_id": "note-1",
                    "alexandria_type": "context",
                    "path": "Contexts/Projects/One.md",
                    "title": "One",
                    "status": "active",
                    "tags": ["search"],
                    "project": "heterarchy-alexandria",
                    "content_hash": "a" * 64,
                    "index_status": "indexed",
                    "wikilink": "[[Contexts/Projects/One]]",
                },
                "excerpt": "best matching excerpt",
                "score": 0.9,
                "chunk_id": "chunk-1",
                "heading_path": "Summary",
            }
        ],
        "total": 1,
    }


def test_mcp_backend_tool_gateway_are_async_http_boundaries() -> None:
    """Public MCP HTTP gateways should remain async boundaries."""
    async_tools = [
        alexandria_search,
        alexandria_search_vault,
        alexandria_archive_context,
        alexandria_delete_context,
        alexandria_rag_status,
        alexandria_read_note,
        alexandria_get_related_notes,
        alexandria_reindex_vault,
        alexandria_get_graph_projection_status,
        alexandria_rebuild_graph_projection,
        alexandria_get_graph_build_status,
        alexandria_validate_note_links,
        alexandria_operational_readiness,
        alexandria_recover,
        alexandria_recovery_run_status,
        alexandria_vault_review_queue,
        alexandria_vault_review_move_plan,
        alexandria_vault_review_apply_moves,
        alexandria_vault_inventory,
        alexandria_vault_path_search,
        alexandria_vault_move_plan,
        alexandria_vault_apply_moves,
        alexandria_list_memory_compact_artifacts,
        alexandria_search_skills,
        alexandria_start_skill_acquisition,
        alexandria_skill_acquisition_job_status,
        alexandria_get_current_memory_compact,
        alexandria_create_memory_compact,
        alexandria_get_memory_compact,
        alexandria_review_memory_compact,
    ]

    assert all(iscoroutinefunction(tool) for tool in async_tools)


def test_mcp_client_sends_backend_http_without_custom_auth_headers() -> None:
    """MCP client should call the backend URL without custom auth headers."""
    client, calls = _client()

    payload = _run_json(
        alexandria_search(
            client,
            ContextSearchRequest(
                query="context recall", limit=3, strategy=RagStrategy.FTS_ONLY
            ),
        )
    )

    request = calls[0]
    request_body = loads_json(request.content or b"{}")
    assert payload == {"ok": True}
    assert request.method == "POST"
    assert str(request.url) == "http://backend:8000/memory/contexts/retrieval/search"
    assert request.headers["accept"] == "application/json"
    assert request.headers["content-type"] == "application/json"
    assert "authorization" not in request.headers
    assert "x-alexandria-operator-key" not in request.headers
    assert request_body == {
        "query": "context recall",
        "strategy": "FTS_ONLY",
        "limit": 3,
    }


def test_mcp_search_forwards_explicit_lifecycle_statuses() -> None:
    client, calls = _client()

    _run_json(
        alexandria_search(
            client,
            ContextSearchRequest(
                query="administrative recall",
                include_lifecycle_statuses=[
                    ContextRecallLifecycleStatus.SUPERSEDED,
                    ContextRecallLifecycleStatus.ARCHIVED,
                ],
            ),
        )
    )

    request_body = loads_json(calls[0].content or b"{}")
    assert request_body == {
        "query": "administrative recall",
        "strategy": "HYBRID",
        "limit": 5,
        "include_lifecycle_statuses": ["SUPERSEDED", "ARCHIVED"],
    }


def test_mcp_search_forwards_explicit_memory_function_preference() -> None:
    """Explicit functional-memory preference should cross MCP without becoming a filter."""
    client, calls = _client()

    _run_json(
        alexandria_search(
            client,
            ContextSearchRequest(
                query="how did we fix this before",
                prefer_memory_functions=[MemoryFunction.EXPERIENTIAL],
            ),
        )
    )

    request_body = loads_json(calls[0].content or b"{}")
    assert request_body == {
        "query": "how did we fix this before",
        "strategy": "HYBRID",
        "limit": 5,
        "prefer_memory_functions": ["EXPERIENTIAL"],
    }


def test_mcp_search_skills_maps_to_search_first_endpoint() -> None:
    """MCP search-first skill tool should call the dedicated librarian endpoint."""
    client, calls = _client()

    payload = _run_json(
        alexandria_search_skills(
            client,
            capability="browser automation",
            task_goal="Run deterministic browser checks",
            project="heterarchy-alexandria",
            environment="pytest",
            required_tools=["playwright"],
            success_criteria=["stable selectors"],
            limit=3,
        )
    )

    request = calls[0]
    body = loads_json(request.content or b"{}")
    assert payload == {"ok": True}
    assert request.method == "POST"
    assert str(request.url) == "http://backend:8000/librarians/skill-library/search"
    assert body == {
        "capability": "browser automation",
        "task_goal": "Run deterministic browser checks",
        "project": "heterarchy-alexandria",
        "environment": "pytest",
        "required_tools": ["playwright"],
        "constraints": [],
        "risk_tolerance": "MEDIUM",
        "success_criteria": ["stable selectors"],
        "limit": 3,
    }


def test_mcp_search_skills_preserves_search_first_decision_payload() -> None:
    """MCP skill search should expose sufficiency evidence and repair handoff."""
    response_payload: JSONValue = {
        "decision": "SEARCH_UNAVAILABLE",
        "query": "browser automation playwright stable selectors",
        "candidates": [],
        "recommended_action": "Repair search before starting acquisition.",
        "gaps": ["Skill library search failed"],
        "decision_explanation": {
            "candidate_count": 0,
            "candidate_ids": [],
            "scores": [],
            "hard_gates": {},
            "match_reasons": {},
            "gaps": ["Skill library search failed"],
            "limitations": ["Skill library search unavailable: disk I/O error"],
        },
        "handoff": {
            "decision": "skill_search_repair_required",
            "repair": {
                "tools": [
                    "alexandria_memory_steward_readiness",
                    "alexandria_reindex_vault",
                ],
                "error": "disk I/O error",
            },
        },
        "search_error": "disk I/O error",
        "token": "backend-secret-token",
    }
    client, calls = _client_with_payload(response_payload)

    payload = _run_json(
        alexandria_search_skills(
            client,
            capability="browser automation",
            task_goal="Run deterministic browser checks",
            required_tools=["playwright"],
            success_criteria=["stable selectors"],
        )
    )

    assert calls[0].method == "POST"
    assert str(calls[0].url) == "http://backend:8000/librarians/skill-library/search"
    assert payload == {
        "decision": "SEARCH_UNAVAILABLE",
        "query": "browser automation playwright stable selectors",
        "candidates": [],
        "recommended_action": "Repair search before starting acquisition.",
        "gaps": ["Skill library search failed"],
        "decision_explanation": {
            "candidate_count": 0,
            "candidate_ids": [],
            "scores": [],
            "hard_gates": {},
            "match_reasons": {},
            "gaps": ["Skill library search failed"],
            "limitations": ["Skill library search unavailable: disk I/O error"],
        },
        "handoff": {
            "decision": "skill_search_repair_required",
            "repair": {
                "tools": [
                    "alexandria_memory_steward_readiness",
                    "alexandria_reindex_vault",
                ],
                "error": "disk I/O error",
            },
        },
        "search_error": "disk I/O error",
    }


def test_mcp_tools_map_to_non_destructive_backend_endpoints() -> None:
    """MCP tools should expose status/archive without deleted CRUD calls."""
    client, calls = _client()

    async def run_tools() -> None:
        await alexandria_archive_context(client, "ctx-1")
        await alexandria_rag_status(client)
        await alexandria_operational_readiness(client)
        await alexandria_recover(
            client,
            dry_run=True,
            trigger="manual",
            actor="pytest",
            idempotency_key="mcp-plan-key",
        )
        await alexandria_recover(
            client,
            dry_run=False,
            trigger="manual",
            actor="pytest",
            idempotency_key="mcp-run-key",
        )
        await alexandria_recovery_run_status(client, "run/1")

    anyio.run(run_tools)

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        ("POST", "/memory/contexts/ctx-1/archive"),
        ("GET", "/memory/contexts/rag/status"),
        ("GET", "/operations/readiness"),
        ("POST", "/operations/recovery/plan"),
        ("POST", "/operations/recovery/runs"),
        ("GET", "/operations/recovery/runs/run%2F1"),
    ]
    recovery_body = loads_json(calls[3].content or b"{}")
    assert recovery_body == {
        "trigger": "manual",
        "actor": "pytest",
        "idempotency_key": "mcp-plan-key",
    }
    recovery_run_body = loads_json(calls[4].content or b"{}")
    assert recovery_run_body == {
        "trigger": "manual",
        "actor": "pytest",
        "idempotency_key": "mcp-run-key",
    }
    assert all(method != "DELETE" for method, _ in methods_and_paths)


def test_mcp_recovery_run_requires_explicit_idempotency_key() -> None:
    """MCP recovery apply should fail closed before backend calls without a key."""
    client, calls = _client()

    async def run_tool() -> None:
        await alexandria_recover(client, dry_run=False, idempotency_key=None)

    try:
        anyio.run(run_tool)
    except ValueError as exc:
        error_message = str(exc)
    else:  # pragma: no cover - failure path for the guard assertion
        raise AssertionError("alexandria_recover accepted apply without a key")

    assert error_message == "idempotency_key is required when recovery dry_run is false"
    assert calls == []


def test_mcp_async_skill_acquisition_tools_use_durable_job_endpoints() -> None:
    """Skill acquisition MCP should expose only autonomous start and polling."""
    client, calls = _client()

    async def run_tools() -> None:
        await alexandria_start_skill_acquisition(
            client,
            prompt="Need browser automation skill",
            project="heterarchy-alexandria",
            task_summary="Browser test blocked.",
            search_snapshot={
                "decision": "NOT_FOUND",
                "gaps": ["No matching browser automation skill."],
            },
        )
        await alexandria_skill_acquisition_job_status(client, "job/1")

    anyio.run(run_tools)

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        ("POST", "/librarians/skill-acquisition-jobs"),
        ("GET", "/librarians/skill-acquisition-jobs/job%2F1"),
    ]
    start_body = loads_json(calls[0].content or b"{}")
    assert start_body == {
        "prompt": "Need browser automation skill",
        "agent_name": "Hermes",
        "project": "heterarchy-alexandria",
        "task_summary": "Browser test blocked.",
        "search_snapshot": {
            "decision": "NOT_FOUND",
            "gaps": ["No matching browser automation skill."],
        },
    }
    assert "provider_id" not in start_body
    assert "librarian_profile_id" not in start_body


def test_mcp_skill_acquisition_status_polling_returns_job_status() -> None:
    """Polling should return sanitized job status without Context Vault writes."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {
            "id": "job/1",
            "status": "ACCEPTED",
            "result_available": False,
            "secret": "provider-secret-material",
            "token": "secret-token",
        },
        {
            "id": "job/1",
            "status": "ACCEPTED",
            "result_available": False,
            "error_message": None,
        },
        {
            "id": "job/1",
            "status": "COMPLETED",
            "skill_id": None,
            "context_id": None,
            "result_available": True,
            "error_message": None,
            "secret": "provider-secret-material",
            "token": "secret-token",
        },
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = responses[len(calls) - 1]
        return httpx.Response(200, content=dumps_json(payload))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    async def run_tools() -> tuple[JSONValue, JSONValue, JSONValue]:
        start_response = await alexandria_start_skill_acquisition(
            client,
            prompt="Need browser automation skill",
        )
        status_pending = await alexandria_skill_acquisition_job_status(client, "job/1")
        status_complete = await alexandria_skill_acquisition_job_status(client, "job/1")
        return start_response, status_pending, status_complete

    start_response, status_pending, status_complete = anyio.run(run_tools)

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        ("POST", "/librarians/skill-acquisition-jobs"),
        ("GET", "/librarians/skill-acquisition-jobs/job%2F1"),
        ("GET", "/librarians/skill-acquisition-jobs/job%2F1"),
    ]
    assert start_response["status"] == "ACCEPTED"
    assert "secret" not in start_response
    assert "token" not in start_response
    assert status_pending["status"] == "ACCEPTED"
    assert status_pending["result_available"] is False
    assert status_pending.get("skill_id") is None
    assert status_pending.get("context_id") is None
    assert status_complete["status"] == "COMPLETED"
    assert status_complete["result_available"] is True
    assert status_complete["skill_id"] is None
    assert status_complete["context_id"] is None
    assert "secret" not in status_complete
    assert "token" not in status_complete


def test_mcp_path_parameters_are_percent_encoded() -> None:
    """MCP path arguments should remain a single backend path segment."""
    client, calls = _client()

    async def run_tools() -> None:
        await alexandria_archive_context(client, "ctx/1?archive=false")
        await alexandria_get_memory_compact(client, "compact/1#anchor")
        await alexandria_skill_acquisition_job_status(client, "job/1")

    anyio.run(run_tools)

    paths = [str(request.url).removeprefix("http://backend:8000") for request in calls]
    assert paths == [
        "/memory/contexts/ctx%2F1%3Farchive%3Dfalse/archive",
        "/memory/compacts/compact%2F1%23anchor",
        "/librarians/skill-acquisition-jobs/job%2F1",
    ]


def test_memory_compact_gateway_supports_agent_reads_and_steward_primitives() -> None:
    """Compact gateway should preserve reads plus internal Steward create/review."""
    client, calls = _client()

    async def run_tools() -> None:
        await alexandria_list_memory_compact_artifacts(
            client,
            project="heterarchy-alexandria",
            status=MemoryCompactStatus.CURRENT,
            limit=3,
        )
        await alexandria_get_current_memory_compact(
            client, project="heterarchy-alexandria"
        )
        await alexandria_create_memory_compact(
            client,
            covered_from="2026-07-01T00:00:00Z",
            covered_to="2026-07-15T00:00:00Z",
            markdown_body=(
                "## Durable Decisions\n"
                "- Current compact decision.\n\n"
                "## Current State\n"
                "- Current compact state.\n\n"
                "## Risks and Blockers\n"
                "- None recorded.\n\n"
                "## Next Actions\n"
                "- Continue validation.\n\n"
                "## Coverage\n"
                "- covered_from: 2026-07-01T00:00:00Z\n"
                "- covered_to: 2026-07-15T00:00:00Z\n"
                "- project: heterarchy-alexandria\n\n"
                "## Evidence Summary\n"
                "- Source note."
            ),
            project="heterarchy-alexandria",
            status=MemoryCompactStatus.CURRENT,
            source_refs=[
                {
                    "source_type": "obsidian_note",
                    "source_id": "note-1",
                    "title": "Source note",
                    "detail_path": "/obsidian/notes/note-1",
                    "source_hash": "hash-before",
                }
            ],
        )
        await alexandria_get_memory_compact(client, "compact/1")
        await alexandria_review_memory_compact(
            client,
            "compact/1",
            source_observations=[
                {
                    "source_id": "note-1",
                    "detail_path": "/obsidian/notes/note-1",
                    "current_source_hash": "hash-after",
                }
            ],
        )

    anyio.run(run_tools)

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        (
            "GET",
            "/memory/compacts?limit=3&offset=0&project=heterarchy-alexandria&status=CURRENT",
        ),
        ("GET", "/memory/compacts/current?project=heterarchy-alexandria"),
        ("POST", "/memory/compacts"),
        ("GET", "/memory/compacts/compact%2F1"),
        ("POST", "/memory/compacts/compact%2F1/review"),
    ]
    create_body = loads_json(calls[2].content or b"{}")
    assert create_body == {
        "covered_from": "2026-07-01T00:00:00Z",
        "covered_to": "2026-07-15T00:00:00Z",
        "markdown_body": (
            "## Durable Decisions\n"
            "- Current compact decision.\n\n"
            "## Current State\n"
            "- Current compact state.\n\n"
            "## Risks and Blockers\n"
            "- None recorded.\n\n"
            "## Next Actions\n"
            "- Continue validation.\n\n"
            "## Coverage\n"
            "- covered_from: 2026-07-01T00:00:00Z\n"
            "- covered_to: 2026-07-15T00:00:00Z\n"
            "- project: heterarchy-alexandria\n\n"
            "## Evidence Summary\n"
            "- Source note."
        ),
        "project": "heterarchy-alexandria",
        "status": "CURRENT",
        "source_refs": [
            {
                "source_type": "obsidian_note",
                "source_id": "note-1",
                "title": "Source note",
                "detail_path": "/obsidian/notes/note-1",
                "source_hash": "hash-before",
            }
        ],
    }
    review_body = loads_json(calls[4].content or b"{}")
    assert review_body == {
        "source_observations": [
            {
                "source_id": "note-1",
                "detail_path": "/obsidian/notes/note-1",
                "current_source_hash": "hash-after",
            }
        ]
    }


def test_mcp_obsidian_tools_map_to_vault_endpoints() -> None:
    """Obsidian MCP tools should expose core vault maintenance, not generic delegation."""
    client, calls = _client()

    async def run_tools() -> None:
        await alexandria_reindex_vault(client)
        await alexandria_search_vault(
            client,
            query="canonical markdown",
            limit=2,
            alexandria_type="context",
            project="heterarchy-alexandria",
            tags=["obsidian"],
        )
        await alexandria_vault_review_queue(
            client,
            project="heterarchy-alexandria",
            scope_path="Alexandria/_Inbox",
            limit=3,
        )
        await alexandria_vault_review_move_plan(
            client,
            project="heterarchy-alexandria",
            scope_path="Alexandria/_Inbox",
            limit=3,
        )
        await alexandria_read_note(client, path="Alexandria/START_HERE.md")
        await alexandria_get_related_notes(
            client, path="Alexandria/START_HERE.md", limit=2
        )

    anyio.run(run_tools)

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        ("POST", "/obsidian/index/rebuild"),
        ("POST", "/obsidian/search"),
        ("POST", "/obsidian/librarian/review-queue"),
        ("POST", "/obsidian/librarian/review-queue/move-plan"),
        ("GET", "/obsidian/notes/by-path?path=Alexandria%2FSTART_HERE.md"),
        (
            "GET",
            "/obsidian/notes/by-path/related?path=Alexandria%2FSTART_HERE.md&limit=2",
        ),
    ]
    assert loads_json(calls[1].content or b"{}") == {
        "query": "canonical markdown",
        "limit": 2,
        "tags": ["obsidian"],
        "alexandria_type": "context",
        "project": "heterarchy-alexandria",
    }
    queue_body = loads_json(calls[2].content or b"{}")
    assert queue_body == {
        "limit": 3,
        "project": "heterarchy-alexandria",
        "scope_path": "Alexandria/_Inbox",
    }
    assert loads_json(calls[3].content or b"{}") == queue_body


def test_mcp_graph_projection_tools_map_to_backend_endpoints() -> None:
    """Graph projection MCP tools should call the explicit REST endpoints."""
    client, calls = _client()

    async def run_tools() -> None:
        await alexandria_get_graph_projection_status(client)
        await alexandria_rebuild_graph_projection(client)
        await alexandria_get_graph_build_status(client)
        await alexandria_validate_note_links(
            client,
            note_id="note-1",
            path="Alexandria/Note 1.md",
            include_resolved_targets=True,
        )
        await alexandria_rebuild_note_graph(
            client,
            note_id="note-1",
            replace_existing_edges=True,
        )

    anyio.run(run_tools)

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        ("GET", "/obsidian/graph/projection/status"),
        ("POST", "/obsidian/graph/projection/rebuild"),
        ("GET", "/obsidian/graph/build/status"),
        (
            "GET",
            "/obsidian/graph/notes/validate-links?"
            "include_resolved_targets=True&note_id=note-1&path=Alexandria%2FNote+1.md",
        ),
        (
            "POST",
            "/obsidian/graph/notes/rebuild?replace_existing_edges=True&note_id=note-1",
        ),
    ]
    assert loads_json(calls[1].content or b"{}") == {}


def test_mcp_explicit_note_write_normalizes_collection_input_before_http_forwarding() -> (
    None
):
    """Explicit MCP writes should forward canonical arrays instead of repr strings."""
    client, calls = _client()

    anyio.run(
        alexandria_create_note,
        client,
        "Metadata Integrity",
        "# Metadata Integrity",
        "context",
        "path",
        None,
        "Contexts/Projects/Metadata Integrity.md",
        "Evidence Intelligence",
        " Evidence Intelligence ",
        "active",
        "mcp",
        {
            "artifact_refs": ("artifact-1", "artifact-2"),
            "evidence_refs": (),
            "source_of_truth": "TRUE",
        },
    )

    request_body = loads_json(calls[0].content or b"{}")
    assert request_body["tags"] == ["Evidence Intelligence"]
    assert request_body["frontmatter"] == {
        "artifact_refs": ["artifact-1", "artifact-2"],
        "evidence_refs": [],
        "source_of_truth": True,
    }


def test_mcp_explicit_note_writes_map_modes_and_identity_selectors() -> None:
    """Explicit note tools should preserve their operation-specific REST contract."""
    client, calls = _client()

    async def run_tools() -> None:
        await alexandria_create_note(
            client,
            "Created",
            "# Created",
            "skill",
            "path",
            note_id="skill-created",
            path="Alexandria/Skills/Drafts/created.md",
        )
        await alexandria_update_note(
            client,
            "Updated",
            "# Updated",
            "skill",
            "note_id",
            note_id="skill-created",
            expected_content_hash="a" * 64,
        )
        await alexandria_upsert_note(
            client,
            "Upserted",
            "# Upserted",
            "skill",
            "path",
            path="Alexandria/Skills/Drafts/upserted.md",
            frontmatter_mode="replace_user_fields",
        )

    anyio.run(run_tools)

    assert [request.url.path for request in calls] == [
        "/obsidian/notes/create",
        "/obsidian/notes/update",
        "/obsidian/notes/upsert",
    ]
    create_body = loads_json(calls[0].content or b"{}")
    update_body = loads_json(calls[1].content or b"{}")
    upsert_body = loads_json(calls[2].content or b"{}")
    assert create_body["match_by"] == "path"
    assert create_body["id"] == "skill-created"
    assert update_body["match_by"] == "note_id"
    assert update_body["expected_content_hash"] == "a" * 64
    assert "tags" not in update_body
    assert "status" not in update_body
    assert "source" not in update_body
    assert "frontmatter" not in update_body
    assert upsert_body["frontmatter_mode"] == "replace_user_fields"


def test_mcp_report_bundle_maps_idempotency_and_verification_contract() -> None:
    """Report bundle MCP calls should forward one bounded orchestration request."""
    client, calls = _client()

    anyio.run(
        alexandria_upsert_report_bundle,
        client,
        "ethereum:2026-08-03",
        {
            "title": "Ethereum Source",
            "path": "Contexts/Projects/Ethereum Source.md",
            "body": "# Ethereum Source",
            "frontmatter": {"project": "crypto", "source_of_truth": "TRUE"},
        },
        [
            {
                "path": "Indexes/Ethereum Month Index.md",
                "relation": "contains",
            }
        ],
    )

    assert calls[0].url.path == "/obsidian/report-bundles/upsert"
    body = loads_json(calls[0].content or b"{}")
    assert body["idempotency_key"] == "ethereum:2026-08-03"
    assert body["source"]["frontmatter"]["source_of_truth"] is True
    assert body["graph_owners"] == [
        {"path": "Indexes/Ethereum Month Index.md", "relation": "contains"}
    ]
    assert body["verify"] == {
        "index_status": True,
        "incoming_edges": True,
        "duplicates": True,
    }


def test_mcp_exact_path_and_canonical_identity_map_without_fuzzy_search() -> None:
    """Identity MCP tools should use focused exact-path and resolver endpoints."""
    client, calls = _client()

    async def run_tools() -> None:
        await alexandria_check_path_exists(client, "Contexts/Projects/Source.md")
        await alexandria_resolve_canonical_identity(
            client,
            "Crypto Intelligence Trader",
            "XRP Morning Read",
            "2026-08-03",
            "XRP",
        )

    anyio.run(run_tools)

    assert [request.method for request in calls] == ["GET", "POST"]
    assert calls[0].url.path == "/obsidian/notes/check-path"
    assert calls[0].url.params["path"] == "Contexts/Projects/Source.md"
    assert calls[1].url.path == "/obsidian/notes/resolve-canonical-identity"
    assert loads_json(calls[1].content or b"{}") == {
        "project": "Crypto Intelligence Trader",
        "report": "XRP Morning Read",
        "date": "2026-08-03",
        "entity": "XRP",
    }


def test_mcp_explicit_note_write_rejects_legacy_collection_repr() -> None:
    """Explicit MCP writes must not reintroduce migrated repr strings."""
    client, calls = _client()

    with pytest.raises(ValueError, match="legacy"):
        anyio.run(
            alexandria_create_note,
            client,
            "Metadata Integrity",
            "# Metadata Integrity",
            "context",
            "path",
            None,
            "Contexts/Projects/Metadata Integrity.md",
            "Evidence Intelligence",
            "('Evidence Intelligence', 'Market')",
            "active",
            "mcp",
            None,
        )

    assert calls == []


def test_mcp_vault_review_apply_requires_confirmation_when_plan_has_moves() -> None:
    """Review apply gateway should fail closed before mutating planned moves."""
    calls: list[RecordedCall] = []
    move_plan: JSONValue = {
        "status": "ready",
        "hard_delete_performed": False,
        "moves": [
            {
                "source_path": "Alexandria/_Inbox/Captures/Captured.md",
                "destination_path": "Alexandria/Contexts/Projects/Captured.md",
            }
        ],
        "skipped": [],
        "ambiguous": [],
    }

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(move_plan))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_vault_review_apply_moves(
            client,
            project="heterarchy-alexandria",
            scope_path="Alexandria/_Inbox",
            limit=3,
        )
    )

    assert [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ] == [("POST", "/obsidian/librarian/review-queue/move-plan")]
    assert payload == {
        "status": "confirmation_required",
        "hard_delete_performed": False,
        "moved": [],
        "skipped": [],
        "ambiguous": [],
        "apply_skipped_reason": "confirm_apply_required",
        "move_plan": move_plan,
    }


def test_mcp_vault_review_apply_confirmed_calls_apply_endpoint() -> None:
    """Confirmed review apply should plan first and then call the apply endpoint."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {
            "status": "ready",
            "hard_delete_performed": False,
            "moves": [
                {
                    "source_path": "Alexandria/_Inbox/Captures/Captured.md",
                    "destination_path": "Alexandria/Contexts/Projects/Captured.md",
                }
            ],
            "skipped": [],
            "ambiguous": [],
        },
        {
            "status": "applied",
            "hard_delete_performed": False,
            "moved": [
                {
                    "source_path": "Alexandria/_Inbox/Captures/Captured.md",
                    "destination_path": "Alexandria/Contexts/Projects/Captured.md",
                }
            ],
        },
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_vault_review_apply_moves(
            client,
            project="heterarchy-alexandria",
            scope_path="Alexandria/_Inbox",
            limit=3,
            report_path="Alexandria/_Ops/Librarian/Reports/review-apply",
            verification_query="canonical markdown",
            confirm_apply=True,
        )
    )

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    apply_body = loads_json(calls[1].content or b"{}")
    assert methods_and_paths == [
        ("POST", "/obsidian/librarian/review-queue/move-plan"),
        ("POST", "/obsidian/librarian/review-queue/apply-moves"),
    ]
    assert apply_body == {
        "limit": 3,
        "reindex": True,
        "project": "heterarchy-alexandria",
        "scope_path": "Alexandria/_Inbox",
        "report_path": "Alexandria/_Ops/Librarian/Reports/review-apply",
        "verification_query": "canonical markdown",
    }
    assert payload["status"] == "applied"


def test_mcp_memory_steward_readiness_combines_health_compact_and_review_queue() -> (
    None
):
    """Readiness should summarize second-brain health in one MCP response."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {
            "fts": "HEALTHY",
            "vector": "HEALTHY",
            "embedding": "HEALTHY",
            "default_strategy": "HYBRID",
            "warnings": [],
        },
        {
            "id": "compact-1",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2026-07-15T00:00:00Z",
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-old"),
        _compact_review_payload("compact-1"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_readiness(
            client, project="heterarchy-alexandria", max_compact_age_days=365_000
        )
    )

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    review_queue_body = loads_json(calls[2].content or b"{}")
    assert methods_and_paths == [
        ("GET", "/memory/contexts/rag/status"),
        ("GET", "/memory/compacts/current?project=heterarchy-alexandria"),
        ("POST", "/obsidian/librarian/review-queue"),
        ("POST", "/memory/compacts/compact-1/review"),
    ]
    assert review_queue_body == {"limit": 20, "project": "heterarchy-alexandria"}
    assert payload["ready"] is True
    assert payload["status"] == "ready"
    assert payload["current_memory_compact"]["id"] == "compact-1"
    assert payload["current_memory_compact"]["max_age_days"] == 365_000
    assert payload["review_queue"]["total"] == 0
    assert payload["review_queue"]["auto_move_candidates"] == 0
    assert payload["review_queue"]["manual_review_required"] == 0
    assert payload["current_memory_compact_review"]["verdict"] == "pass"
    assert payload["warnings"] == []
    assert payload["next_actions"] == []


def test_mcp_memory_steward_readiness_flags_stale_current_compact() -> None:
    """Readiness should fail closed when the current compact is too old."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "HEALTHY"},
        {
            "id": "compact-old",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2000-01-01T00:00:00Z",
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-old"),
        _compact_review_payload("compact-old"),
        _compact_review_payload("compact-old"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_readiness(
            client, project="heterarchy-alexandria", max_compact_age_days=30
        )
    )

    assert payload["ready"] is False
    assert payload["status"] == "needs_attention"
    assert payload["current_memory_compact"]["id"] == "compact-old"
    assert payload["current_memory_compact"]["max_age_days"] == 30
    assert payload["current_memory_compact"]["age_days"] > 30
    assert payload["warnings"] == ["current_memory_compact_stale"]
    assert payload["next_actions"] == [
        {
            "priority": 20,
            "code": "refresh_current_memory_compact",
            "tool": "alexandria_memory_steward_refresh_current_compact",
            "summary": "Refresh the CURRENT Memory Compact from readiness evidence.",
            "dry_run_first": True,
        }
    ]


def test_mcp_memory_steward_readiness_flags_missing_current_compact_timestamp() -> None:
    """Readiness should preserve missing timestamp warnings from compact API."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "HEALTHY"},
        {
            "id": "compact-missing-timestamp",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2026-07-17T00:00:00Z",
            "warnings": ["memory_compact_timestamp_missing"],
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-missing-timestamp"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_readiness(
            client, project="heterarchy-alexandria", max_compact_age_days=365_000
        )
    )

    assert payload["ready"] is False
    assert payload["status"] == "needs_attention"
    assert payload["current_memory_compact"]["id"] == "compact-missing-timestamp"
    assert payload["warnings"] == ["current_memory_compact_timestamp_missing"]
    assert payload["next_actions"] == [
        {
            "priority": 20,
            "code": "refresh_current_memory_compact",
            "tool": "alexandria_memory_steward_refresh_current_compact",
            "summary": "Refresh the CURRENT Memory Compact from readiness evidence.",
            "dry_run_first": True,
        }
    ]


def test_mcp_memory_steward_readiness_flags_source_hash_changed_current_compact() -> (
    None
):
    """Readiness should mark CURRENT stale when source evidence hash changed."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "HEALTHY"},
        {
            "id": "compact-source-changed",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2999-01-01T00:00:00Z",
            "source_refs": [
                {
                    "source_type": "CONTEXT",
                    "source_id": "ctx-1",
                    "title": "Decision source",
                    "detail_path": "/memory/contexts/ctx-1",
                    "source_hash": "hash-before",
                    "current_source_hash": "hash-after",
                }
            ],
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-source-changed"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_readiness(
            client, project="heterarchy-alexandria", max_compact_age_days=30
        )
    )

    assert payload["ready"] is False
    assert payload["warnings"] == ["current_memory_compact_stale"]
    assert (
        payload["current_memory_compact"]["source_refs"][0]["source_hash"]
        == "hash-before"
    )
    assert (
        payload["current_memory_compact"]["source_refs"][0]["current_source_hash"]
        == "hash-after"
    )


def test_mcp_memory_steward_readiness_flags_blocked_current_compact_review() -> None:
    """Readiness should surface the latest CURRENT compact review verdict."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "HEALTHY"},
        {
            "id": "compact-blocked",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2999-01-01T00:00:00Z",
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-blocked", verdict="blocked"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_readiness(
            client, project="heterarchy-alexandria", max_compact_age_days=30
        )
    )

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        ("GET", "/memory/contexts/rag/status"),
        ("GET", "/memory/compacts/current?project=heterarchy-alexandria"),
        ("POST", "/obsidian/librarian/review-queue"),
        ("POST", "/memory/compacts/compact-blocked/review"),
    ]
    assert payload["ready"] is False
    assert payload["current_memory_compact_review"]["verdict"] == "blocked"
    assert payload["warnings"] == ["current_memory_compact_review_blocked"]
    assert payload["next_actions"] == [
        {
            "priority": 20,
            "code": "refresh_current_memory_compact",
            "tool": "alexandria_memory_steward_refresh_current_compact",
            "summary": "Refresh the CURRENT Memory Compact from readiness evidence.",
            "dry_run_first": True,
        }
    ]


def test_mcp_memory_steward_readiness_returns_blocked_payload_when_rag_status_fails() -> (
    None
):
    """Readiness should fail closed when RAG status cannot be loaded."""
    calls: list[RecordedCall] = []

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, content=dumps_json({"detail": "rag unavailable"}))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_readiness(
            client, project="heterarchy-alexandria", max_compact_age_days=30
        )
    )

    paths = [str(request.url).removeprefix("http://backend:8000") for request in calls]
    assert paths == ["/memory/contexts/rag/status"]
    assert payload["ready"] is False
    assert payload["status"] == "needs_attention"
    assert payload["warnings"] == ["rag_status_unavailable"]
    assert payload["rag"]["warnings"] == ["HTTP 503: rag unavailable"]
    assert payload["next_actions"] == [
        {
            "priority": 10,
            "code": "repair_rag_index",
            "tool": "alexandria_reindex_vault",
            "summary": "Repair or rebuild retrieval indexes before trusting answers.",
            "dry_run_first": False,
        }
    ]


def test_mcp_memory_steward_readiness_flags_attention_items() -> None:
    """Readiness should surface degraded RAG, missing compact, and queue backlog."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "REINDEX_REQUIRED", "embedding": "HEALTHY"},
        {},
        {
            "items": [
                {
                    "id": "draft-1",
                    "suggested_destination_path": "Alexandria/Skills/Active/Draft.md",
                    "requires_human_review": True,
                },
                {
                    "id": "inbox-1",
                    "suggested_destination_path": (
                        "Alexandria/Contexts/Projects/Inbox.md"
                    ),
                    "requires_human_review": False,
                },
            ],
            "total": 2,
        },
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(alexandria_memory_steward_readiness(client))

    assert payload["ready"] is False
    assert payload["status"] == "needs_attention"
    assert payload["warnings"] == [
        "rag_vector_not_healthy",
        "current_memory_compact_missing",
        "vault_review_queue_not_empty",
    ]
    assert payload["review_queue"]["total"] == 2
    assert payload["review_queue"]["auto_move_candidates"] == 1
    assert payload["review_queue"]["manual_review_required"] == 1
    assert payload["next_actions"] == [
        {
            "priority": 10,
            "code": "repair_rag_index",
            "tool": "alexandria_reindex_vault",
            "summary": "Repair or rebuild retrieval indexes before trusting answers.",
            "dry_run_first": False,
        },
        {
            "priority": 20,
            "code": "refresh_current_memory_compact",
            "tool": "alexandria_memory_steward_refresh_current_compact",
            "summary": "Refresh the CURRENT Memory Compact from readiness evidence.",
            "dry_run_first": True,
        },
        {
            "priority": 30,
            "code": "curate_vault_review_queue",
            "tool": "alexandria_vault_review_move_plan",
            "summary": "Plan safe vault moves for automatic review candidates.",
            "dry_run_first": True,
        },
        {
            "priority": 40,
            "code": "review_manual_vault_queue",
            "tool": "alexandria_vault_review_queue",
            "summary": "Inspect queue items that require human judgment.",
            "dry_run_first": True,
        },
    ]


def test_mcp_memory_steward_readiness_separates_manual_review_queue_action() -> None:
    """Manual-only review queues should not recommend an automatic move plan."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "HEALTHY"},
        {
            "id": "compact-1",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2999-01-01T00:00:00Z",
        },
        {
            "items": [
                {
                    "id": "skill-draft",
                    "suggested_destination_path": "Alexandria/Skills/Active/Draft.md",
                    "requires_human_review": True,
                }
            ],
            "total": 1,
        },
        _compact_review_payload("compact-1"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_readiness(
            client,
            project="heterarchy-alexandria",
            max_compact_age_days=365_000,
        )
    )

    assert payload["ready"] is False
    assert payload["warnings"] == ["vault_review_queue_not_empty"]
    assert payload["review_queue"]["auto_move_candidates"] == 0
    assert payload["review_queue"]["manual_review_required"] == 1
    assert payload["next_actions"] == [
        {
            "priority": 40,
            "code": "review_manual_vault_queue",
            "tool": "alexandria_vault_review_queue",
            "summary": "Inspect queue items that require human judgment.",
            "dry_run_first": True,
        }
    ]


def test_mcp_memory_steward_refresh_current_compact_plans_stale_compact_refresh() -> (
    None
):
    """Refresh tool should draft a CURRENT compact without mutating by default."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "HEALTHY"},
        {
            "id": "compact-old",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2000-01-01T00:00:00Z",
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-old"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_refresh_current_compact(
            client,
            project="heterarchy-alexandria",
            max_compact_age_days=30,
            apply=False,
            covered_to="2026-07-15T00:00:00Z",
        )
    )

    paths = [str(request.url).removeprefix("http://backend:8000") for request in calls]
    assert paths == [
        "/memory/contexts/rag/status",
        "/memory/compacts/current?project=heterarchy-alexandria",
        "/obsidian/librarian/review-queue",
        "/memory/compacts/compact-old/review",
    ]
    assert payload["status"] == "refresh_required"
    assert payload["created"] is None
    assert payload["compact_draft"]["covered_from"] == "2000-01-01T00:00:00Z"
    assert payload["compact_draft"]["covered_to"] == "2026-07-15T00:00:00Z"
    assert payload["compact_draft"]["source_refs"][0]["source_id"] == "compact-old"
    assert "current_memory_compact_stale" in payload["readiness"]["warnings"]


def test_mcp_memory_steward_refresh_current_compact_applies_stale_compact_refresh() -> (
    None
):
    """Refresh tool should create a CURRENT compact and re-check readiness when applied."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "HEALTHY"},
        {
            "id": "compact-old",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2000-01-01T00:00:00Z",
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-old"),
        {"id": "compact-new", "project": "heterarchy-alexandria", "status": "CURRENT"},
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "HEALTHY"},
        {
            "id": "compact-new",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2999-01-01T00:00:00Z",
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-new"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_refresh_current_compact(
            client,
            project="heterarchy-alexandria",
            max_compact_age_days=30,
            apply=True,
            covered_to="2026-07-15T00:00:00Z",
        )
    )

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    create_body = loads_json(calls[4].content or b"{}")
    assert methods_and_paths == [
        ("GET", "/memory/contexts/rag/status"),
        ("GET", "/memory/compacts/current?project=heterarchy-alexandria"),
        ("POST", "/obsidian/librarian/review-queue"),
        ("POST", "/memory/compacts/compact-old/review"),
        ("POST", "/memory/compacts"),
        ("GET", "/memory/contexts/rag/status"),
        ("GET", "/memory/compacts/current?project=heterarchy-alexandria"),
        ("POST", "/obsidian/librarian/review-queue"),
        ("POST", "/memory/compacts/compact-new/review"),
    ]
    assert create_body["project"] == "heterarchy-alexandria"
    assert create_body["covered_from"] == "2000-01-01T00:00:00Z"
    assert create_body["covered_to"] == "2026-07-15T00:00:00Z"
    assert create_body["status"] == "CURRENT"
    assert create_body["source_refs"][0]["source_id"] == "compact-old"
    assert payload["status"] == "refreshed"
    assert payload["created"]["id"] == "compact-new"
    assert payload["post_refresh_readiness"]["ready"] is True


def test_mcp_memory_steward_refresh_current_compact_blocks_apply_when_rag_unhealthy() -> (
    None
):
    """Refresh apply should fail closed on RAG health even when force is requested."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "REINDEX_REQUIRED"},
        {
            "id": "compact-old",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2000-01-01T00:00:00Z",
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-old"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_refresh_current_compact(
            client,
            project="heterarchy-alexandria",
            max_compact_age_days=30,
            apply=True,
            force=True,
            covered_to="2026-07-15T00:00:00Z",
        )
    )

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        ("GET", "/memory/contexts/rag/status"),
        ("GET", "/memory/compacts/current?project=heterarchy-alexandria"),
        ("POST", "/obsidian/librarian/review-queue"),
        ("POST", "/memory/compacts/compact-old/review"),
    ]
    assert payload["status"] == "blocked_by_rag_health"
    assert payload["created"] is None
    assert payload["blocked_reasons"] == ["rag_embedding_not_healthy"]
    assert payload["blocked_next_actions"] == [
        {
            "priority": 10,
            "code": "repair_rag_index",
            "tool": "alexandria_reindex_vault",
            "summary": "Repair or rebuild retrieval indexes before trusting answers.",
            "dry_run_first": False,
        }
    ]


def test_mcp_memory_steward_refresh_current_compact_blocks_apply_on_rag_warnings() -> (
    None
):
    """Refresh apply should fail closed when RAG status includes warnings."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {
            "fts": "HEALTHY",
            "vector": "HEALTHY",
            "embedding": "HEALTHY",
            "warnings": ["embedding index status check failed: REINDEX_REQUIRED"],
        },
        {
            "id": "compact-old",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2000-01-01T00:00:00Z",
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-old"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_refresh_current_compact(
            client,
            project="heterarchy-alexandria",
            max_compact_age_days=30,
            apply=True,
            force=True,
            covered_to="2026-07-15T00:00:00Z",
        )
    )

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        ("GET", "/memory/contexts/rag/status"),
        ("GET", "/memory/compacts/current?project=heterarchy-alexandria"),
        ("POST", "/obsidian/librarian/review-queue"),
        ("POST", "/memory/compacts/compact-old/review"),
    ]
    assert payload["status"] == "blocked_by_rag_health"
    assert payload["created"] is None
    assert payload["blocked_reasons"] == ["rag_status_warnings_present"]
    assert "rag_status_warnings_present" in payload["readiness"]["warnings"]
    assert payload["readiness"]["rag"]["warnings"] == [
        "embedding index status check failed: REINDEX_REQUIRED"
    ]


def test_mcp_memory_steward_refresh_current_compact_blocks_apply_when_rag_status_fails() -> (
    None
):
    """Refresh apply should return a blocked plan when RAG status lookup fails."""
    calls: list[RecordedCall] = []

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, content=dumps_json({"detail": "rag unavailable"}))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_refresh_current_compact(
            client,
            project="heterarchy-alexandria",
            max_compact_age_days=30,
            apply=True,
            force=True,
            covered_to="2026-07-15T00:00:00Z",
        )
    )

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [("GET", "/memory/contexts/rag/status")]
    assert payload["status"] == "blocked_by_rag_health"
    assert payload["created"] is None
    assert payload["blocked_reasons"] == ["rag_status_unavailable"]
    assert payload["readiness"]["warnings"] == ["rag_status_unavailable"]


def test_mcp_memory_steward_refresh_current_compact_blocks_apply_for_manual_review() -> (
    None
):
    """Refresh apply should not run while librarian review is blocked."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "HEALTHY"},
        {
            "id": "compact-old",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2000-01-01T00:00:00Z",
        },
        {
            "items": [
                {
                    "suggested_destination_path": None,
                    "requires_human_review": True,
                }
            ],
            "total": 1,
        },
        _compact_review_payload("compact-old"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_refresh_current_compact(
            client,
            project="heterarchy-alexandria",
            max_compact_age_days=30,
            apply=True,
            covered_to="2026-07-15T00:00:00Z",
        )
    )

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        ("GET", "/memory/contexts/rag/status"),
        ("GET", "/memory/compacts/current?project=heterarchy-alexandria"),
        ("POST", "/obsidian/librarian/review-queue"),
        ("POST", "/memory/compacts/compact-old/review"),
    ]
    assert payload["status"] == "blocked_by_vault_review"
    assert payload["created"] is None
    assert payload["blocked_reasons"] == ["vault_manual_review_required"]
    assert payload["blocked_next_actions"] == [
        {
            "priority": 40,
            "code": "review_manual_vault_queue",
            "tool": "alexandria_vault_review_queue",
            "summary": "Inspect queue items that require human judgment.",
            "dry_run_first": True,
        }
    ]


def test_mcp_memory_steward_refresh_current_compact_blocks_apply_for_review_verdict() -> (
    None
):
    """Refresh apply should not run when CURRENT compact review is blocked."""
    calls: list[RecordedCall] = []
    responses: list[JSONValue] = [
        {"fts": "HEALTHY", "vector": "HEALTHY", "embedding": "HEALTHY"},
        {
            "id": "compact-blocked",
            "project": "heterarchy-alexandria",
            "status": "CURRENT",
            "updated_at": "2000-01-01T00:00:00Z",
        },
        {"items": [], "total": 0},
        _compact_review_payload("compact-blocked", verdict="blocked"),
    ]

    async def fake_transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(responses[len(calls) - 1]))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(
            base_url="http://backend:8000",
            timeout=12.0,
        ),
        transport=httpx.MockTransport(fake_transport),
    )

    payload = _run_json(
        alexandria_memory_steward_refresh_current_compact(
            client,
            project="heterarchy-alexandria",
            max_compact_age_days=30,
            apply=True,
            covered_to="2026-07-15T00:00:00Z",
        )
    )

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    assert methods_and_paths == [
        ("GET", "/memory/contexts/rag/status"),
        ("GET", "/memory/compacts/current?project=heterarchy-alexandria"),
        ("POST", "/obsidian/librarian/review-queue"),
        ("POST", "/memory/compacts/compact-blocked/review"),
    ]
    assert payload["status"] == "blocked_by_vault_review"
    assert payload["created"] is None
    assert payload["blocked_reasons"] == ["current_memory_compact_review_blocked"]
    assert payload["blocked_next_actions"] == []


def test_mcp_librarian_vault_operation_tools_map_to_safe_vault_endpoints() -> None:
    """Manual librarian vault operation tools should call typed safe endpoints."""
    client, calls = _client()
    moves = [
        {
            "source_path": "Alexandria/_Inbox/Captures/Loose.md",
            "destination_path": "Alexandria/Contexts/Projects/Loose.md",
            "reason": "classify captured context",
        }
    ]

    async def run_tools() -> None:
        await alexandria_vault_inventory(client, scope_path="Alexandria/_Inbox")
        await alexandria_vault_path_search(
            client, query="Loose", scope_path="Alexandria/_Inbox"
        )
        await alexandria_vault_move_plan(client, moves=moves)
        await alexandria_vault_apply_moves(
            client,
            moves=moves,
            report_path="Alexandria/_Ops/Librarian/Reports/manual-apply",
            verification_query="Loose",
        )

    anyio.run(run_tools)

    methods_and_paths = [
        (request.method, str(request.url).removeprefix("http://backend:8000"))
        for request in calls
    ]
    inventory_body = loads_json(calls[0].content or b"{}")
    path_search_body = loads_json(calls[1].content or b"{}")
    move_plan_body = loads_json(calls[2].content or b"{}")
    apply_body = loads_json(calls[3].content or b"{}")

    assert methods_and_paths == [
        ("POST", "/obsidian/librarian/vault/inventory"),
        ("POST", "/obsidian/librarian/vault/path-search"),
        ("POST", "/obsidian/librarian/vault/move-plan"),
        ("POST", "/obsidian/librarian/vault/apply-moves"),
    ]
    assert inventory_body == {"scope_path": "Alexandria/_Inbox"}
    assert path_search_body == {
        "query": "Loose",
        "scope_path": "Alexandria/_Inbox",
    }
    assert move_plan_body == {"moves": moves}
    assert apply_body == {
        "moves": moves,
        "reindex": True,
        "report_path": "Alexandria/_Ops/Librarian/Reports/manual-apply",
        "verification_query": "Loose",
    }


def test_mcp_context_delete_tool_maps_to_hard_delete_endpoint() -> None:
    """Context delete MCP tool should call the hard-delete context endpoint."""
    client, calls = _client()

    _run_json(alexandria_delete_context(client, "ctx/1"))

    assert calls[0].method == "DELETE"
    assert str(calls[0].url) == "http://backend:8000/memory/contexts/ctx%2F1"


def test_mcp_context_supersede_tool_maps_to_canonical_endpoint() -> None:
    """Context supersede MCP tool should preserve source-qualified IDs."""
    client, calls = _client()

    _run_json(
        alexandria_supersede_context(
            client,
            "obsidian:old/1",
            "obsidian:new/1",
        )
    )

    assert calls[0].method == "POST"
    assert str(calls[0].url) == (
        "http://backend:8000/memory/contexts/obsidian%3Aold%2F1/supersede"
    )
    assert loads_json(calls[0].content or b"{}") == {
        "replacement_context_id": "obsidian:new/1"
    }


def test_fastapi_app_accepts_tunnel_host_for_streamable_http_mcp() -> None:
    """FastAPI should expose MCP to reverse-tunnel hosts without 421."""
    app = create_app(AppConfig(_env_file=None, mcp_auth_mode="none"))
    initialize_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0.1.0"},
        },
    }

    try:
        with TestClient(
            app, base_url="https://b973-121-135-181-35.ngrok-free.app"
        ) as client:
            response = client.post(
                "/mcp/",
                json=initialize_request,
                headers={"Accept": "application/json, text/event-stream"},
            )
    finally:
        default_app.state.container.wire(packages=_ROUTER_PACKAGES)

    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "heterarchy-alexandria"


def test_mcp_v2_transport_security_allows_tunnel_host() -> None:
    """Non-local binds should explicitly disable localhost-only protection."""
    tunnel_security = mcp_transport_security(DEFAULT_MCP_TRANSPORT_HOST)

    assert tunnel_security is not None
    assert tunnel_security.enable_dns_rebinding_protection is False
    assert mcp_transport_security("localhost") is None


def test_fastmcp_server_registers_required_alexandria_tools() -> None:
    """FastMCP should expose focused acquisition and core maintenance contracts."""
    client, _ = _client()
    server = build_mcp_server(client=client)

    tools = anyio.run(server.list_tools)
    names = {tool.name for tool in tools}

    assert len(names) == 52
    assert {
        "alexandria_search",
        "alexandria_search_skills",
        "alexandria_start_skill_acquisition",
        "alexandria_skill_acquisition_job_status",
        "alexandria_memory_steward_readiness",
        "alexandria_memory_steward_refresh_current_compact",
        "alexandria_vault_review_queue",
        "alexandria_vault_review_move_plan",
        "alexandria_vault_review_apply_moves",
        "alexandria_vault_inventory",
        "alexandria_vault_path_search",
        "alexandria_vault_move_plan",
        "alexandria_vault_apply_moves",
        "alexandria_operational_readiness",
        "alexandria_recover",
        "alexandria_read_note",
        "alexandria_search_vault",
        "alexandria_create_note",
        "alexandria_update_note",
        "alexandria_upsert_note",
    } <= names
    assert {
        "alexandria_complete_skill_acquisition",
        "alexandria_ask_librarian",
        "alexandria_librarian_brief_preview",
        "alexandria_librarian_route_preview",
        "alexandria_librarian_job_status",
        "alexandria_librarian_oauth_start",
        "alexandria_librarian_oauth_poll",
        "alexandria_librarian_oauth_status",
        "alexandria_librarian_oauth_refresh",
        "alexandria_librarian_readiness",
        "alexandria_librarian_refresh_current_compact",
        "alexandria_librarian_review_queue",
        "alexandria_librarian_review_move_plan",
        "alexandria_librarian_review_apply_moves",
        "alexandria_librarian_vault_inventory",
        "alexandria_librarian_vault_path_search",
        "alexandria_librarian_vault_move_plan",
        "alexandria_librarian_vault_apply_moves",
        "alexandria_ask_obsidian_librarian",
        "alexandria_create_memory_compact",
        "alexandria_mark_memory_compact_current",
        "alexandria_archive_memory_compact",
        "alexandria_review_memory_compact",
        "alexandria_delete_memory_compact",
        "alexandria_get_memory_reconciliation_result",
        "alexandria_mark_memory_conflict_reviewing",
    }.isdisjoint(names)
