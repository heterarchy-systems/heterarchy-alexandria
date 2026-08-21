"""MCP librarian compact refresh draft contract tests."""

from __future__ import annotations

import anyio
from datetime import datetime
from pathlib import Path

from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.mcp_server.tools.memory_compacts.memory_steward_compact_refresh import (
    refresh_compact_payload,
)
from app.mcp_server.type_validate.memory.memory_steward_readiness_schemas import (
    CurrentCompactPayload,
    RagStatusPayload,
    ReadinessSummaryPayload,
    ReviewQueuePayload,
)


def _readiness_summary() -> ReadinessSummaryPayload:
    return ReadinessSummaryPayload(
        ready=False,
        status="NEEDS_ATTENTION",
        rag=RagStatusPayload(
            fts="HEALTHY",
            vector="HEALTHY",
            embedding="HEALTHY",
        ),
        current_memory_compact=CurrentCompactPayload(
            id="compact-old",
            project="heterarchy-alexandria",
            status="CURRENT",
            updated_at="2000-01-01T00:00:00Z",
            age_days=9_000,
            max_age_days=30,
        ),
        review_queue=ReviewQueuePayload(total=0),
        warnings=("current_memory_compact_stale",),
    )


def test_refresh_compact_payload_links_all_source_refs_in_evidence_summary() -> None:
    """Refresh drafts should satisfy Memory Compact source-ref evidence review."""
    draft = refresh_compact_payload(
        project="heterarchy-alexandria",
        readiness=_readiness_summary(),
        covered_to="2026-07-15T00:00:00Z",
    )

    body = draft.markdown_body

    assert draft.source_refs
    for source_ref in draft.source_refs:
        assert (
            source_ref.source_id in body
            or source_ref.detail_path in body
            or source_ref.title in body
        )


def test_refresh_compact_payload_passes_memory_compact_current_review_gate(
    tmp_path: Path,
) -> None:
    """Refresh drafts should be accepted by the real CURRENT review gate."""

    async def scenario() -> tuple[str, str, int | None, int | None]:
        draft = refresh_compact_payload(
            project="heterarchy-alexandria",
            readiness=_readiness_summary(),
            covered_to="2026-07-15T00:00:00Z",
        )
        service = MemoryCompactService(
            repository=ObsidianMemoryCompactRepository(
                vault_path=tmp_path / "vault",
                relative_dir="Alexandria/Memory Compacts",
            )
        )
        compact = await service.create(
            MemoryCompactCreate(
                project=draft.project,
                covered_from=_parse_timestamp(draft.covered_from),
                covered_to=_parse_timestamp(draft.covered_to),
                markdown_body=draft.markdown_body,
                status=MemoryCompactStatus.CURRENT,
                source_refs=[
                    MemoryCompactSourceRefCreate(
                        source_type=source_ref.source_type,
                        source_id=source_ref.source_id,
                        title=source_ref.title,
                        detail_path=source_ref.detail_path,
                    )
                    for source_ref in draft.source_refs
                ],
            )
        )
        return (
            compact.status.value,
            compact.review_verdict.value if compact.review_verdict else "",
            compact.review_score,
            compact.review_max_score,
        )

    status, review_verdict, review_score, review_max_score = anyio.run(scenario)

    assert {
        "status": status,
        "review_verdict": review_verdict,
        "review_score": review_score,
        "review_max_score": review_max_score,
    } == {
        "status": "CURRENT",
        "review_verdict": "pass",
        "review_score": 20,
        "review_max_score": 20,
    }


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
