"""Typed HTTP and MCP contracts for the high-level relate tool."""

from __future__ import annotations

import anyio
import httpx
import pytest
from pydantic import ValidationError

from app.mcp_server.backend_api_client import (
    AlexandriaApiClient,
    AlexandriaApiSettings,
)
from app.mcp_server.tools.obsidian.obsidian_relation_backend_gateway import (
    alexandria_relate,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianRelationType
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
)
from app.obsidian.interface.schemas.obsidian.obsidian_relation_schema import (
    ObsidianRelateRequestSchema,
    ObsidianRelateResponse,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject


def _payload() -> JSONObject:
    """Return one complete typed relate response payload."""
    return {
        "completion_status": "COMPLETED",
        "idempotency_key": "typed-relate",
        "replayed": False,
        "source_note_id": "source",
        "target_note_id": "target",
        "relation": "contains",
        "source_path": "Indexes/Source.md",
        "target_path": "Indexes/Target.md",
        "operation": "updated",
        "content_hash": "a" * 64,
        "storage_status": "stored",
        "metadata_status": "indexed",
        "fts_status": "indexed",
        "graph_edge_index_status": "indexed",
        "graph_projection_status": "ready",
        "source_link_verified": True,
        "target_backlink_verified": True,
        "related_notes_verified": True,
        "graph_edge_id": "edge-1",
        "projection_run_id": "run-1",
        "warnings": [],
        "errors": [],
    }


def test_relate_request_uses_strict_sha256_cas_contract() -> None:
    """The public CAS field accepts only a hexadecimal SHA-256 digest."""
    request = ObsidianRelateRequestSchema(
        source_note_id="source",
        target_note_id="target",
        relation=ObsidianRelationType.CONTAINS,
        idempotency_key="typed-relate",
        expected_source_hash="A" * 64,
    )
    assert request.to_command().expected_source_hash == "a" * 64
    with pytest.raises(ValidationError):
        ObsidianRelateRequestSchema(
            source_note_id="source",
            target_note_id="target",
            relation=ObsidianRelationType.CONTAINS,
            idempotency_key="typed-relate",
            expected_source_hash="g" * 64,
        )


def test_relate_mcp_gateway_validates_typed_response_model() -> None:
    """MCP gateway returns the declared response model after HTTP validation."""
    calls: list[httpx.Request] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=dumps_json(_payload()))

    client = AlexandriaApiClient(
        AlexandriaApiSettings(base_url="http://backend:8000", timeout=12.0),
        transport=httpx.MockTransport(transport),
    )
    request = ObsidianRelateRequestSchema(
        source_note_id="source",
        target_note_id="target",
        relation=ObsidianRelationType.CONTAINS,
        idempotency_key="typed-relate",
    )

    response = anyio.run(alexandria_relate, client, request)

    assert isinstance(response, ObsidianRelateResponse)
    assert response.completion_status == ObsidianRelateCompletionStatus.COMPLETED.value
    assert calls[0].url.path == "/obsidian/notes/relate"
    body = loads_json(calls[0].content)
    assert body == {
        "source_note_id": "source",
        "target_note_id": "target",
        "relation": "contains",
        "idempotency_key": "typed-relate",
    }
