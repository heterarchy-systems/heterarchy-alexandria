"""Typed MCP gateway and output-schema tests for verified upsert."""

from __future__ import annotations

import asyncio
from typing import cast

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.server_runtime import build_mcp_server
from app.mcp_server.tools.obsidian.verified_upsert_backend_gateway import (
    alexandria_verified_upsert,
    alexandria_verify,
)
from app.obsidian.interface.schemas.obsidian.obsidian_verified_upsert_schema import (
    ObsidianVerifiedUpsertRequestSchema,
    ObsidianVerifiedUpsertResponse,
    ObsidianVerifiedUpsertSelectorSchema,
    ObsidianVerifiedUpsertVerificationResponse,
)
from app.shared.serialization.orjson_codec import dumps_json


class _FakeApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((path, payload))
        if path.endswith("/verify"):
            return {
                "source_readable": True,
                "canonical_identity_resolved": True,
                "indexed": True,
                "vector_current": None,
                "graph_current": None,
                "duplicate_safe": True,
                "temporal_authority_consistent": None,
                "note_id": "note-1",
                "canonical_path": "Alexandria/Jobs/eth.md",
                "content_hash": "a" * 64,
                "version": 1,
                "warnings": [],
            }
        return {
            "operation": "created",
            "idempotency_key": "run-1",
            "logical_identity": {
                "project": "Project",
                "report": "Morning Read",
                "date": "2026-09-08",
                "entity": "ETH",
                "edition": None,
            },
            "note_id": "note-1",
            "canonical_path": "Alexandria/Jobs/eth.md",
            "content_hash": "a" * 64,
            "version": 1,
            "storage_status": "verified",
            "readback_verified": True,
            "metadata_status": "verified",
            "fts_status": "verified",
            "vector_status": "unknown",
            "graph_edge_index_status": "verified",
            "graph_projection_status": "stale",
            "duplicate_safety": "verified",
            "warnings": [],
            "error_code": None,
        }


def _request() -> ObsidianVerifiedUpsertRequestSchema:
    return ObsidianVerifiedUpsertRequestSchema.model_validate_json(
        dumps_json(
            {
                "identity": {
                    "project": "Project",
                    "report": "Morning Read",
                    "date": "2026-09-08",
                    "entity": "ETH",
                },
                "title": "ETH Morning Read",
                "body": "fact",
                "alexandria_type": "job_plan",
                "idempotency_key": "run-1",
            }
        )
    )


def test_verified_upsert_gateways_validate_request_and_response_models() -> None:
    """MCP transport returns typed models and sends only the strict request shape."""

    async def scenario() -> None:
        fake = _FakeApiClient()
        request = _request()
        result = await alexandria_verified_upsert(
            cast(AlexandriaApiClient, fake),
            request,
        )
        verification = await alexandria_verify(
            cast(AlexandriaApiClient, fake),
            ObsidianVerifiedUpsertSelectorSchema(
                identity=request.identity,
            ),
        )
        assert isinstance(result, ObsidianVerifiedUpsertResponse)
        assert result.operation == "created"
        assert isinstance(verification, ObsidianVerifiedUpsertVerificationResponse)
        assert verification.indexed is True
        assert fake.calls[0][0] == "/obsidian/verified-upsert"
        assert "metadata" not in fake.calls[0][1]

    asyncio.run(scenario())


def test_verified_upsert_mcp_tools_expose_real_typed_schemas() -> None:
    """The public MCP descriptors expose request/response object contracts."""

    async def scenario() -> None:
        server = build_mcp_server(client=cast(AlexandriaApiClient, _FakeApiClient()))
        tools = await server.list_tools()
        by_name = {tool.name: tool for tool in tools}
        upsert = by_name["alexandria_verified_upsert"]
        verify = by_name["alexandria_verify"]
        assert set(upsert.input_schema["properties"]) == {"request"}
        upsert_output = cast(dict[str, object], upsert.output_schema)
        assert {
            "operation",
            "logical_identity",
            "storage_status",
            "readback_verified",
            "metadata_status",
            "fts_status",
            "vector_status",
            "graph_edge_index_status",
            "graph_projection_status",
            "duplicate_safety",
        }.issubset(cast(dict[str, object], upsert_output["properties"]))
        assert set(verify.input_schema["properties"]) == {"request"}
        verify_output = cast(dict[str, object], verify.output_schema)
        assert {
            "source_readable",
            "canonical_identity_resolved",
            "indexed",
            "duplicate_safe",
        }.issubset(cast(dict[str, object], verify_output["properties"]))

    asyncio.run(scenario())
