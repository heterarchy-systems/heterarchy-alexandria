"""HTTP request-body schema and JSON-mode boundary evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from dependency_injector import providers
from fastapi.testclient import TestClient

from app.main import app
from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.contracts.recall_contracts import RecallRequest
from app.memory.domain.entities.memory_cycle import (
    MemoryCycleBuckets,
    MemoryCycleResult,
)
from app.memory.domain.entities.recall import RecallResult, RecallTrace
from app.memory.domain.event_enum.context_enums import (
    ContextScope,
    RagStrategy,
)
from app.memory.domain.event_enum.memory_cycle_enums import MemoryCycleStatus
from app.memory.domain.event_enum.recall_enums import RecallOutcome, RecallScopeMode

_HIGH_LEVEL_POST_PATHS: Final[tuple[str, ...]] = (
    "/memory/recall",
    "/memory/cycle",
    "/obsidian/verified-upsert",
    "/obsidian/verified-upsert/verify",
    "/obsidian/notes/relate",
    "/obsidian/managed-specs/execute",
)


class _RecallHttpFake:
    """Typed recall collaborator proving a valid body reaches application code."""

    def __init__(self) -> None:
        self.requests: list[RecallRequest] = []

    async def recall(self, request: RecallRequest) -> RecallResult:
        self.requests.append(request)
        return RecallResult(
            query=request.query,
            scope_mode=RecallScopeMode.AUTO,
            recall_scopes=(ContextScope.GLOBAL,),
            effective_strategy=RagStrategy.AUTO,
            outcome=RecallOutcome.SEARCH_EXHAUSTED,
            warnings=(),
            matches=(),
            context_pack="# Alexandria Context Pack\n",
            trace=RecallTrace(
                stages=(),
                skipped_scopes=(),
                fallback_expansion=(),
                degraded_subsystems=(),
                outcome=RecallOutcome.SEARCH_EXHAUSTED,
                confidence=0.0,
                search_call_count=0,
            ),
        )


class _MemoryCycleHttpFake:
    """Typed cycle collaborator proving a valid aware window reaches application code."""

    def __init__(self) -> None:
        self.requests: list[MemoryCycleRequest] = []

    async def execute(self, request: MemoryCycleRequest) -> MemoryCycleResult:
        self.requests.append(request)
        return MemoryCycleResult(
            operation=request.operation,
            status=MemoryCycleStatus.PREVIEW,
            idempotency_key=request.idempotency_key,
            plan_hash="a" * 64,
            project=request.project,
            workspace_id=request.workspace_id,
            scope=request.scope.value,
            window_start=request.window_start,
            window_end=request.window_end,
            replayed=False,
            scanned=0,
            total_available=0,
            candidate_count=0,
            source_snapshot=(),
            current_compact=None,
            buckets=MemoryCycleBuckets(),
            child_outcomes=(),
            compact_change=None,
            phases=(),
            warnings=(),
            elapsed_ms=0.0,
        )


def _resolved_request_schema(path: str) -> dict[str, object]:
    """Resolve one route's application/json request schema from OpenAPI."""
    openapi = app.openapi()
    body = openapi["paths"][path]["post"]["requestBody"]
    schema = body["content"]["application/json"]["schema"]
    if "$ref" not in schema:
        return schema
    component_name = schema["$ref"].rsplit("/", maxsplit=1)[-1]
    return openapi["components"]["schemas"][component_name]


def test_all_agent_facing_composites_publish_json_request_bodies() -> None:
    """OpenAPI exposes every high-level HTTP input, including root unions."""
    openapi = app.openapi()

    for path in _HIGH_LEVEL_POST_PATHS:
        operation = openapi["paths"][path]["post"]
        assert "requestBody" in operation
        assert "application/json" in operation["requestBody"]["content"]
        assert _resolved_request_schema(path)

    for path in ("/memory/cycle", "/obsidian/managed-specs/execute"):
        schema = _resolved_request_schema(path)
        discriminator = schema.get("discriminator")
        assert isinstance(discriminator, dict)
        mapping = discriminator.get("mapping")
        assert isinstance(mapping, dict)
        assert discriminator.get("propertyName") == "operation"
        assert set(mapping) == (
            {"dry_run", "apply"} if path == "/memory/cycle" else {"prepare", "complete"}
        )


def test_recall_and_cycle_json_timestamps_reach_typed_application_requests() -> None:
    """JSON timestamps remain accepted while nested schemas stay strict."""
    recall_fake = _RecallHttpFake()
    cycle_fake = _MemoryCycleHttpFake()
    with (
        app.state.container.recall_service.override(providers.Object(recall_fake)),
        app.state.container.memory_cycle_service.override(providers.Object(cycle_fake)),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        recall_response = client.post(
            "/memory/recall",
            json={
                "query": "historical decision",
                "as_of": "2026-09-08T00:00:00Z",
            },
        )
        cycle_response = client.post(
            "/memory/cycle",
            json={
                "operation": "dry_run",
                "project": "Alexandria",
                "window_start": "2026-09-08T00:00:00Z",
                "window_end": "2026-09-08T01:00:00+00:00",
                "idempotency_key": "http-schema-cycle",
            },
        )

    assert recall_response.status_code == 200, recall_response.text
    assert cycle_response.status_code == 200, cycle_response.text
    assert recall_fake.requests[0].as_of == datetime(2026, 9, 8, tzinfo=UTC)
    assert cycle_fake.requests[0].window_start == datetime(2026, 9, 8, tzinfo=UTC)
    assert cycle_fake.requests[0].window_end == datetime(2026, 9, 8, 1, tzinfo=UTC)


def test_high_level_http_bodies_reject_extra_scope_hash_and_missing_identity() -> None:
    """Boundary migration preserves strict rejection before application effects."""
    with TestClient(app, raise_server_exceptions=False) as client:
        extra = client.post(
            "/memory/recall",
            json={"query": "query", "unexpected": True},
        )
        invalid_scope = client.post(
            "/memory/cycle",
            json={
                "operation": "dry_run",
                "project": "Alexandria",
                "scope": "AGENT",
                "window_start": "2026-09-08T00:00:00Z",
                "window_end": "2026-09-08T01:00:00Z",
                "idempotency_key": "invalid-scope",
            },
        )
        missing_project = client.post(
            "/memory/cycle",
            json={
                "operation": "dry_run",
                "window_start": "2026-09-08T00:00:00Z",
                "window_end": "2026-09-08T01:00:00Z",
                "idempotency_key": "missing-project",
            },
        )
        invalid_hash = client.post(
            "/obsidian/notes/relate",
            json={
                "source_note_id": "source",
                "target_note_id": "target",
                "relation": "contains",
                "idempotency_key": "invalid-hash",
                "expected_source_hash": "g" * 64,
            },
        )

    assert extra.status_code == 422, extra.text
    assert invalid_scope.status_code == 422, invalid_scope.text
    assert missing_project.status_code == 422, missing_project.text
    assert invalid_hash.status_code == 422, invalid_hash.text
