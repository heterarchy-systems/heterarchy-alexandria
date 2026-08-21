"""Memory Compact router contract tests."""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest
from app.main import app
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.memory.interface.routers.memory_compact_router import (
    create_memory_compact,
    mark_memory_compact_current,
)
from app.memory.interface.schemas.memory_compact.memory_compact_schema import (
    MemoryCompactCreateRequest,
)
from app.shared.serialization.orjson_codec import dumps_json
from app.shared.types.extra_types import JSONObject
from fastapi import HTTPException
from fastapi.testclient import TestClient
from tests.shared.provider_overrides import override_library_provider


def _open_service(vault_path: Path) -> MemoryCompactService:
    return MemoryCompactService(
        repository=ObsidianMemoryCompactRepository(
            vault_path=vault_path,
            relative_dir="Alexandria/Memory Compacts",
        )
    )


def _compact_note_path(vault_path: Path, compact_id: str) -> Path:
    notes_dir = vault_path / "Alexandria" / "Memory Compacts"
    matches = list(notes_dir.rglob(f"{compact_id}.md"))
    assert len(matches) == 1
    return matches[0]


def _compact_body(covered_from: str, covered_to: str) -> str:
    return f"""## Durable Decisions
- Keep this compact as the current project summary.

## Current State
- Durable Memory Compact is current, scoped, and ready for follow-up work.

## Risks and Blockers
- No active blockers; validation risk is tracked through source refs.

## Next Actions
- Continue from this compact.

## Coverage
- covered_from: {covered_from}
- covered_to: {covered_to}
- project: heterarchy-alexandria

## Evidence Summary
- Context source supports the compact claims.
"""


def _payload(
    status: str = "CURRENT",
    *,
    covered_from: str = "2026-05-01T00:00:00Z",
    covered_to: str = "2026-05-10T00:00:00Z",
    source_id: str = "ctx-1",
) -> JSONObject:
    return {
        "project": "heterarchy-alexandria",
        "covered_from": covered_from,
        "covered_to": covered_to,
        "markdown_body": _compact_body(covered_from, covered_to),
        "status": status,
        "source_refs": [
            {
                "source_type": "CONTEXT",
                "source_id": source_id,
                "title": "Context source",
                "detail_path": f"/memory/contexts/{source_id}",
            }
        ],
    }


def _request(payload: JSONObject) -> MemoryCompactCreateRequest:
    """Validate one decoded HTTP payload with strict JSON semantics.

    Args:
        payload: JSON-compatible Memory Compact request payload.

    Returns:
        Strictly validated Memory Compact create request.
    """
    return MemoryCompactCreateRequest.model_validate_json(dumps_json(payload))


def test_memory_compact_api_hard_deletes_obsidian_note(tmp_path: Path) -> None:
    """Memory Compact delete should remove the Obsidian Markdown artifact."""
    service = _open_service(tmp_path / "vault")
    with (
        override_library_provider("memory_compact_service", service),
        override_library_provider(
            "context_service", _FakeContextService(RagHealthState.HEALTHY)
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        create_response = client.post("/memory/compacts", json=_payload())
        compact_id = create_response.json()["id"]
        note_path = _compact_note_path(tmp_path / "vault", compact_id)
        delete_response = client.delete(f"/memory/compacts/{compact_id}")
        get_response = client.get(f"/memory/compacts/{compact_id}")
        list_response = client.get(
            "/memory/compacts", params={"project": "heterarchy-alexandria"}
        )
        current_response = client.get(
            "/memory/compacts/current", params={"project": "heterarchy-alexandria"}
        )

    assert create_response.status_code == 201
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert get_response.status_code == 404
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 0
    assert current_response.status_code == 404
    assert not note_path.exists()


def test_memory_compact_api_exposes_current_archive_lifecycle(tmp_path: Path) -> None:
    """Memory Compact API should expose list/current/get/archive lifecycle."""
    service = _open_service(tmp_path / "vault")
    with (
        override_library_provider("memory_compact_service", service),
        override_library_provider(
            "context_service", _FakeContextService(RagHealthState.HEALTHY)
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        create_response = client.post("/memory/compacts", json=_payload())
        compact_id = create_response.json()["id"]
        note_path = _compact_note_path(tmp_path / "vault", compact_id)
        current_response = client.get(
            "/memory/compacts/current", params={"project": "heterarchy-alexandria"}
        )
        get_response = client.get(f"/memory/compacts/{compact_id}")
        list_response = client.get(
            "/memory/compacts", params={"project": "heterarchy-alexandria"}
        )
        archive_response = client.post(f"/memory/compacts/{compact_id}/archive")
        archived_get_response = client.get(f"/memory/compacts/{compact_id}")

    assert create_response.status_code == 201
    assert create_response.json()["status"] == "CURRENT"
    assert create_response.json()["source_refs"][0]["source_id"] == "ctx-1"
    assert current_response.status_code == 200
    current_payload = current_response.json()
    assert current_payload["id"] == compact_id
    assert current_payload["review_verdict"] == "pass"
    assert current_payload["review_score"] is not None
    assert current_payload["review_max_score"] == 20
    assert current_payload["reviewed_at"] is not None
    assert get_response.status_code == 200
    assert get_response.json()["markdown_body"].startswith("## Durable Decisions")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "ARCHIVED"
    assert (
        archive_response.json()["source_refs"] == create_response.json()["source_refs"]
    )
    assert archived_get_response.status_code == 200
    assert archived_get_response.json()["status"] == "ARCHIVED"
    assert archived_get_response.json()["source_refs"][0]["source_id"] == "ctx-1"
    assert note_path.exists()
    assert "source_refs:" in note_path.read_text(encoding="utf-8")


def test_memory_compact_api_marks_duplicate_signature_response(
    tmp_path: Path,
) -> None:
    """Duplicate signature creates no new note and returns a dedupe marker."""
    service = _open_service(tmp_path / "vault")
    with (
        override_library_provider("memory_compact_service", service),
        override_library_provider(
            "context_service", _FakeContextService(RagHealthState.HEALTHY)
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        first_response = client.post("/memory/compacts", json=_payload())
        duplicate_payload = _payload()
        duplicate_payload["source_refs"] = list(
            reversed(duplicate_payload["source_refs"])
        )
        duplicate_response = client.post("/memory/compacts", json=duplicate_payload)
        list_response = client.get(
            "/memory/compacts", params={"project": "heterarchy-alexandria"}
        )
        note_paths = list(
            (tmp_path / "vault" / "Alexandria" / "Memory Compacts").rglob("*.md")
        )

    assert first_response.status_code == 201
    assert first_response.json()["deduplicated"] is False
    assert duplicate_response.status_code == 201
    assert duplicate_response.json()["id"] == first_response.json()["id"]
    assert duplicate_response.json()["deduplicated"] is True
    assert list_response.json()["total"] == 1
    assert len(note_paths) == 1


def test_current_memory_compact_response_warns_when_stale(tmp_path: Path) -> None:
    """Stale CURRENT should remain readable but expose a warning reason."""
    service = _open_service(tmp_path / "vault")
    with (
        override_library_provider("memory_compact_service", service),
        override_library_provider(
            "context_service", _FakeContextService(RagHealthState.HEALTHY)
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        create_response = client.post("/memory/compacts", json=_payload())
        compact_id = create_response.json()["id"]
        note_path = _compact_note_path(tmp_path / "vault", compact_id)
        note = note_path.read_text(encoding="utf-8")
        note = note.replace(
            create_response.json()["updated_at"],
            "2000-01-01T00:00:00+00:00",
        ).replace(
            create_response.json()["reviewed_at"],
            "2000-01-01T00:00:00+00:00",
        )
        note_path.write_text(note, encoding="utf-8")

        current_response = client.get(
            "/memory/compacts/current",
            params={"project": "heterarchy-alexandria", "max_compact_age_days": 30},
        )

    assert current_response.status_code == 200
    body = current_response.json()
    assert body["id"] == compact_id
    assert body["status"] == "CURRENT"
    assert body["warnings"] == ["current_memory_compact_stale"]


def test_current_memory_compact_response_warns_when_timestamp_missing(
    tmp_path: Path,
) -> None:
    """Legacy CURRENT notes without updated_at should expose a warning reason."""
    service = _open_service(tmp_path / "vault")
    with (
        override_library_provider("memory_compact_service", service),
        override_library_provider(
            "context_service", _FakeContextService(RagHealthState.HEALTHY)
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        create_response = client.post("/memory/compacts", json=_payload())
        compact_id = create_response.json()["id"]
        note_path = _compact_note_path(tmp_path / "vault", compact_id)
        note = note_path.read_text(encoding="utf-8")
        note = "\n".join(
            line
            for line in note.splitlines()
            if not line.startswith("updated_at:")
            and not line.startswith("reviewed_at:")
        )
        note_path.write_text(note, encoding="utf-8")

        current_response = client.get(
            "/memory/compacts/current",
            params={
                "project": "heterarchy-alexandria",
                "max_compact_age_days": 365_000,
            },
        )

    assert current_response.status_code == 200
    body = current_response.json()
    assert body["id"] == compact_id
    assert body["status"] == "CURRENT"
    assert body["warnings"] == ["current_memory_compact_timestamp_missing"]


def test_memory_compact_api_reviews_quality_rubric(tmp_path: Path) -> None:
    """Review endpoint should expose verdict, scores, refs, stale reasons, actions."""
    service = _open_service(tmp_path / "vault")
    payload = _payload()
    payload["source_refs"] = [
        {
            "source_type": "CONTEXT",
            "source_id": "ctx-hash",
            "title": "Context source",
            "detail_path": "/memory/contexts/ctx-hash",
            "source_hash": "hash-before",
        }
    ]
    with (
        override_library_provider("memory_compact_service", service),
        override_library_provider(
            "context_service", _FakeContextService(RagHealthState.HEALTHY)
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        create_response = client.post("/memory/compacts", json=payload)
        compact_id = create_response.json()["id"]
        review_response = client.post(
            f"/memory/compacts/{compact_id}/review",
            json={
                "source_observations": [
                    {
                        "source_id": "ctx-hash",
                        "detail_path": "/memory/contexts/ctx-hash",
                        "current_source_hash": "hash-after",
                    }
                ]
            },
        )

    body = review_response.json()
    assert create_response.status_code == 201
    assert review_response.status_code == 200
    assert body["compact_id"] == compact_id
    assert body["verdict"] == "blocked"
    assert body["stale_reasons"] == ["source_hash_mismatch:ctx-hash"]
    assert body["recommended_actions"] == ["refresh_source_evidence"]
    assert {score["code"] for score in body["scores"]} >= {
        "evidence_completeness",
        "freshness",
        "contradiction_handling",
    }


def test_memory_compact_api_filters_by_dates_when_requested(tmp_path: Path) -> None:
    """Memory Compact API should filter by coverage overlap."""
    service = _open_service(tmp_path / "vault")
    with (
        override_library_provider("memory_compact_service", service),
        override_library_provider(
            "context_service", _FakeContextService(RagHealthState.HEALTHY)
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        may_response = client.post(
            "/memory/compacts",
            json=_payload(
                "DRAFT",
                covered_from="2026-05-01T00:00:00Z",
                covered_to="2026-05-10T00:00:00Z",
                source_id="ctx-may",
            ),
        )
        june_response = client.post(
            "/memory/compacts",
            json=_payload(
                "DRAFT",
                covered_from="2026-06-01T00:00:00Z",
                covered_to="2026-06-10T00:00:00Z",
                source_id="ctx-june",
            ),
        )
        coverage_response = client.get(
            "/memory/compacts",
            params={
                "project": "heterarchy-alexandria",
                "covered_after": "2026-05-05T00:00:00Z",
                "covered_before": "2026-05-06T23:59:59Z",
            },
        )
        naive_response = client.get(
            "/memory/compacts",
            params={"covered_after": "2026-05-05T00:00:00"},
        )

    assert may_response.status_code == 201
    assert june_response.status_code == 201
    assert coverage_response.status_code == 200
    coverage_payload = coverage_response.json()
    assert coverage_payload["total"] == 1
    assert [item["id"] for item in coverage_payload["items"]] == [
        may_response.json()["id"]
    ]
    assert naive_response.status_code == 422


def test_memory_compact_api_rejects_non_iso_datetime_without_server_error(
    tmp_path: Path,
) -> None:
    """Memory Compact API should return validation errors for invalid datetimes."""
    service = _open_service(tmp_path / "vault")
    with (
        override_library_provider("memory_compact_service", service),
        override_library_provider(
            "context_service", _FakeContextService(RagHealthState.HEALTHY)
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        payload = _payload()
        payload["covered_from"] = 123
        response = client.post("/memory/compacts", json=payload)

    assert response.status_code == 422


def test_memory_compact_api_rejects_blank_required_source_ref_fields(
    tmp_path: Path,
) -> None:
    """Whitespace-only required source-ref fields should fail schema validation."""
    service = _open_service(tmp_path / "vault")
    with (
        override_library_provider("memory_compact_service", service),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        payload = _payload("DRAFT")
        payload["source_refs"] = [
            {
                "source_type": "   ",
                "source_id": "ctx-blank-source-type",
                "title": "Context source",
                "detail_path": "/memory/contexts/ctx-blank-source-type",
            }
        ]
        response = client.post("/memory/compacts", json=payload)

    assert response.status_code == 422


class _FakeContextService:
    def __init__(
        self, embedding: RagHealthState, *, warnings: list[str] | None = None
    ) -> None:
        self._embedding = embedding
        self._warnings = [] if warnings is None else warnings

    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.HEALTHY,
            embedding=self._embedding,
            default_strategy=(
                RagStrategy.HYBRID
                if self._embedding is RagHealthState.HEALTHY
                else RagStrategy.FTS_ONLY
            ),
            model_name="test-model",
            dimensions=3,
            fingerprint={"provider": "test"},
            warnings=self._warnings,
        )


class _FailingContextService:
    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        raise RuntimeError("rag status failed")


def test_create_current_route_rejects_missing_required_sections(
    tmp_path: Path,
) -> None:
    """CURRENT compacts should include the PRD-required quality sections."""

    async def scenario() -> tuple[int, object, int]:
        service = _open_service(tmp_path / "vault")
        payload = _payload("CURRENT")
        payload["markdown_body"] = "## Current State\n- Too thin."
        with pytest.raises(HTTPException) as raised:
            await create_memory_compact(
                request=_request(payload),
                service=service,
                context_service=_FakeContextService(RagHealthState.HEALTHY),
            )
        _items, total = await service.list_compacts(project="heterarchy-alexandria")
        return raised.value.status_code, raised.value.detail, total

    status_code, detail, total = anyio.run(scenario)

    assert status_code == 400
    assert detail == (
        "Current memory compact missing required sections: "
        "Durable Decisions, Risks and Blockers, Next Actions, Coverage, "
        "Evidence Summary"
    )
    assert total == 0


def test_create_current_route_blocks_when_rag_unhealthy(tmp_path: Path) -> None:
    """Creating CURRENT directly should fail closed when RAG is not healthy."""

    async def scenario() -> tuple[int, object, int]:
        service = _open_service(tmp_path / "vault")
        with pytest.raises(HTTPException) as raised:
            await create_memory_compact(
                request=_request(_payload("CURRENT")),
                service=service,
                context_service=_FakeContextService(RagHealthState.REINDEX_REQUIRED),
            )
        items, total = await service.list_compacts(project="heterarchy-alexandria")
        assert items == []
        return raised.value.status_code, raised.value.detail, total

    status_code, detail, total = anyio.run(scenario)

    assert status_code == 400
    assert detail == {
        "error": "blocked_by_rag_health",
        "gate_status": "blocked",
        "components": ["rag_embedding_reindex_required"],
        "warnings": [],
        "recommended_recovery_tools": ["alexandria_reindex_context_embeddings"],
        "retryable": True,
    }
    assert total == 0


def test_create_current_route_blocks_when_rag_status_lookup_fails(
    tmp_path: Path,
) -> None:
    """Creating CURRENT should fail closed when the RAG status check fails."""

    async def scenario() -> tuple[int, object, int]:
        service = _open_service(tmp_path / "vault")
        with pytest.raises(HTTPException) as raised:
            await create_memory_compact(
                request=_request(_payload("CURRENT")),
                service=service,
                context_service=_FailingContextService(),
            )
        items, total = await service.list_compacts(project="heterarchy-alexandria")
        assert items == []
        return raised.value.status_code, raised.value.detail, total

    status_code, detail, total = anyio.run(scenario)

    assert status_code == 400
    assert detail == {
        "error": "blocked_by_rag_health",
        "gate_status": "blocked",
        "components": ["rag_status_unavailable"],
        "warnings": [],
        "recommended_recovery_tools": ["alexandria_check_context_rag_status"],
        "retryable": True,
    }
    assert total == 0


def test_create_current_route_blocks_when_rag_health_has_warnings(
    tmp_path: Path,
) -> None:
    """Creating CURRENT should fail closed when RAG health reports warnings."""

    async def scenario() -> tuple[int, object, int]:
        service = _open_service(tmp_path / "vault")
        with pytest.raises(HTTPException) as raised:
            await create_memory_compact(
                request=_request(_payload("CURRENT")),
                service=service,
                context_service=_FakeContextService(
                    RagHealthState.HEALTHY,
                    warnings=["Vector retrieval degraded."],
                ),
            )
        items, total = await service.list_compacts(project="heterarchy-alexandria")
        assert items == []
        return raised.value.status_code, raised.value.detail, total

    status_code, detail, total = anyio.run(scenario)

    assert status_code == 400
    assert detail == {
        "error": "blocked_by_rag_health",
        "gate_status": "blocked",
        "components": ["rag_status_warnings_present"],
        "warnings": ["Vector retrieval degraded."],
        "recommended_recovery_tools": ["alexandria_check_context_rag_status"],
        "retryable": True,
    }
    assert total == 0


def test_create_current_route_allows_when_rag_healthy(tmp_path: Path) -> None:
    """Creating CURRENT directly should still work when RAG health is green."""

    async def scenario() -> tuple[str, MemoryCompactStatus, dict[str, object] | None]:
        service = _open_service(tmp_path / "vault")
        current = await create_memory_compact(
            request=_request(_payload("CURRENT")),
            service=service,
            context_service=_FakeContextService(RagHealthState.HEALTHY),
        )
        gate = None if current.rag_gate is None else current.rag_gate.model_dump()
        return current.id, current.status, gate

    compact_id, compact_status, rag_gate = anyio.run(scenario)

    assert compact_id
    assert compact_status == MemoryCompactStatus.CURRENT
    assert rag_gate is not None
    assert rag_gate["gate_status"] == "passed"
    assert rag_gate["checked_at"] is not None
    assert rag_gate["fingerprint"] == {"provider": "test"}


def test_mark_current_route_blocks_when_rag_unhealthy(tmp_path: Path) -> None:
    """mark-current should fail closed when the RAG healthy gate is not green."""

    async def scenario() -> tuple[int, object, MemoryCompactStatus]:
        service = _open_service(tmp_path / "vault")
        created = await service.create(_request(_payload("DRAFT")).to_create())
        with pytest.raises(HTTPException) as raised:
            await mark_memory_compact_current(
                compact_id=created.id,
                service=service,
                context_service=_FakeContextService(RagHealthState.REINDEX_REQUIRED),
            )
        loaded = await service.get(created.id)
        return raised.value.status_code, raised.value.detail, loaded.status

    status_code, detail, loaded_status = anyio.run(scenario)

    assert status_code == 400
    assert detail == {
        "error": "blocked_by_rag_health",
        "gate_status": "blocked",
        "components": ["rag_embedding_reindex_required"],
        "warnings": [],
        "recommended_recovery_tools": ["alexandria_reindex_context_embeddings"],
        "retryable": True,
    }
    assert loaded_status == MemoryCompactStatus.DRAFT


def test_mark_current_route_blocks_when_rag_status_lookup_fails(
    tmp_path: Path,
) -> None:
    """mark-current should fail closed when the RAG status check fails."""

    async def scenario() -> tuple[int, object, MemoryCompactStatus]:
        service = _open_service(tmp_path / "vault")
        created = await service.create(_request(_payload("DRAFT")).to_create())
        with pytest.raises(HTTPException) as raised:
            await mark_memory_compact_current(
                compact_id=created.id,
                service=service,
                context_service=_FailingContextService(),
            )
        loaded = await service.get(created.id)
        return raised.value.status_code, raised.value.detail, loaded.status

    status_code, detail, loaded_status = anyio.run(scenario)

    assert status_code == 400
    assert detail == {
        "error": "blocked_by_rag_health",
        "gate_status": "blocked",
        "components": ["rag_status_unavailable"],
        "warnings": [],
        "recommended_recovery_tools": ["alexandria_check_context_rag_status"],
        "retryable": True,
    }
    assert loaded_status == MemoryCompactStatus.DRAFT


def test_mark_current_route_allows_when_rag_healthy(tmp_path: Path) -> None:
    """mark-current should still promote when source refs and RAG health are valid."""

    async def scenario() -> tuple[str, MemoryCompactStatus, dict[str, object] | None]:
        service = _open_service(tmp_path / "vault")
        created = await service.create(_request(_payload("DRAFT")).to_create())
        current = await mark_memory_compact_current(
            compact_id=created.id,
            service=service,
            context_service=_FakeContextService(RagHealthState.HEALTHY),
        )
        gate = None if current.rag_gate is None else current.rag_gate.model_dump()
        return current.id, current.status, gate

    compact_id, compact_status, rag_gate = anyio.run(scenario)

    assert compact_id
    assert compact_status == MemoryCompactStatus.CURRENT
    assert rag_gate is not None
    assert rag_gate["gate_status"] == "passed"
    assert rag_gate["checked_at"] is not None
    assert rag_gate["fingerprint"] == {"provider": "test"}
