"""MCP contracts for queued, bounded maintenance work."""

from __future__ import annotations

from inspect import iscoroutinefunction

import anyio
import httpx

from app.mcp_server.backend_api_client import (
    AlexandriaApiClient,
    AlexandriaApiSettings,
)
from app.mcp_server.server_runtime import build_mcp_server
from app.mcp_server.tools.operations.maintenance_backend_gateway import (
    alexandria_get_maintenance_job,
    alexandria_get_maintenance_queue_status,
    alexandria_list_maintenance_dead_letters,
    alexandria_purge_maintenance_dead_letters,
    alexandria_reindex_context_embeddings,
    alexandria_replay_maintenance_dead_letter,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json


def _client() -> tuple[AlexandriaApiClient, list[httpx.Request]]:
    calls: list[httpx.Request] = []

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


def test_maintenance_mcp_gateways_are_async_http_boundaries() -> None:
    """Maintenance tool gateways must remain non-blocking MCP boundaries."""
    assert all(
        iscoroutinefunction(tool)
        for tool in (
            alexandria_reindex_context_embeddings,
            alexandria_get_maintenance_job,
            alexandria_get_maintenance_queue_status,
            alexandria_list_maintenance_dead_letters,
            alexandria_purge_maintenance_dead_letters,
            alexandria_replay_maintenance_dead_letter,
        )
    )


def test_reindex_gateway_submits_a_normalized_bounded_job() -> None:
    """Reindex MCP input should be validated before queue submission."""
    client, calls = _client()

    result = anyio.run(
        alexandria_reindex_context_embeddings,
        client,
        " scheduler ",
        " morning-read ",
        125,
        True,
    )

    request = calls[0]
    assert result == {"ok": True}
    assert request.method == "POST"
    assert str(request.url) == (
        "http://backend:8000/operations/maintenance/embedding-reindex/jobs"
    )
    assert loads_json(request.content) == {
        "requested_by": "scheduler",
        "source_id": "morning-read",
        "limit": 125,
        "force": True,
    }


def test_maintenance_job_gateway_uses_one_encoded_path_segment() -> None:
    """A caller-provided job id must not alter the backend route shape."""
    client, calls = _client()

    result = anyio.run(
        alexandria_get_maintenance_job,
        client,
        " job/1 ",
    )

    request = calls[0]
    assert result == {"ok": True}
    assert request.method == "GET"
    assert str(request.url) == (
        "http://backend:8000/operations/maintenance/jobs/job%2F1"
    )


def test_maintenance_queue_status_gateway_is_read_only() -> None:
    """Queue status should map to the aggregate read-only backend endpoint."""
    client, calls = _client()

    result = anyio.run(alexandria_get_maintenance_queue_status, client)

    request = calls[0]
    assert result == {"ok": True}
    assert request.method == "GET"
    assert str(request.url) == (
        "http://backend:8000/operations/maintenance/queue/status"
    )


def test_dead_letter_list_gateway_bounds_and_maps_limit() -> None:
    """Dead-letter listing should map to the bounded read-only endpoint."""
    client, calls = _client()

    result = anyio.run(
        alexandria_list_maintenance_dead_letters,
        client,
        25,
    )

    request = calls[0]
    assert result == {"ok": True}
    assert request.method == "GET"
    assert request.url.params["limit"] == "25"


def test_dead_letter_purge_gateway_maps_to_delete_endpoint() -> None:
    """Purging dead letters should map to the DELETE backend endpoint."""
    client, calls = _client()

    result = anyio.run(alexandria_purge_maintenance_dead_letters, client)

    request = calls[0]
    assert result == {"ok": True}
    assert request.method == "DELETE"
    assert str(request.url) == "http://backend:8000/operations/maintenance/dead-letters"


def test_dead_letter_replay_gateway_uses_one_encoded_path_segment() -> None:
    """A caller-provided dead-letter entry id must not alter the route shape."""
    client, calls = _client()

    result = anyio.run(
        alexandria_replay_maintenance_dead_letter,
        client,
        " 5/1 ",
    )

    request = calls[0]
    assert result == {"ok": True}
    assert request.method == "POST"
    assert str(request.url) == (
        "http://backend:8000/operations/maintenance/dead-letters/5%2F1/replay"
    )


def test_fastmcp_registers_queued_reindex_and_job_observation_tools() -> None:
    """The public MCP surface should expose submission and observation together."""
    client, _ = _client()
    server = build_mcp_server(client=client)

    tools = anyio.run(server.list_tools)
    names = {tool.name for tool in tools}

    assert {
        "alexandria_reindex_context_embeddings",
        "alexandria_get_maintenance_job",
        "alexandria_get_maintenance_queue_status",
        "alexandria_list_maintenance_dead_letters",
        "alexandria_purge_maintenance_dead_letters",
        "alexandria_replay_maintenance_dead_letter",
    } <= names
