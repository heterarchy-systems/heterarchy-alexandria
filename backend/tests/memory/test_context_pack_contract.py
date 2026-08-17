"""Contract tests for recall metadata and bounded Context Packs."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.memory.application.retrieval.context_pack import (
    MAX_CONTEXT_PACK_CHARACTERS,
    build_context_pack,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextPack,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    RagStrategy,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.memory.interface.schemas.context.context_mapping import (
    match_payload,
    pack_payload,
)
from app.memory.interface.schemas.context.context_schema import (
    ContextSearchMatchResponse,
)

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def _match(
    context_id: str,
    *,
    scope: ContextScope = ContextScope.PROJECT,
    score: float = 1.0,
    content: str = "bounded context content",
    status: ContextStorageStatus = ContextStorageStatus.SAVED,
    fts_score: float | None = 1.0,
    vector_score: float | None = None,
    evidence_refs: list[str] | None = None,
    lifecycle_status: str | None = None,
    retrieval_source: str | None = None,
    canonical_context_id: str | None = None,
    source_agent: str = "Hermes",
    chunk_suffix: str = "1",
) -> ContextSearchMatch:
    metadata = ContextMetadataPayload(
        provenance={
            "artifact_refs": ["artifact://test-results.json"],
            "evidence_refs": evidence_refs or [],
        }
    )
    if lifecycle_status is not None:
        metadata["lifecycle_status"] = lifecycle_status
    if retrieval_source is not None:
        metadata["source_surface"] = retrieval_source
    if canonical_context_id is not None:
        metadata["canonical_context_id"] = canonical_context_id
    context = ContextRecord(
        id=context_id,
        kind=ContextKind.HANDOFF,
        title=f"Context {context_id}",
        summary="summary",
        content=content,
        content_format=ContextContentFormat.MARKDOWN,
        project="heterarchy-alexandria",
        scope=scope,
        workspace_id="workspace-1",
        agent_id="agent-1" if scope is ContextScope.AGENT else None,
        user_id=None,
        session_id="session-1" if scope is ContextScope.SESSION else None,
        visibility=scope,
        source_agent=source_agent,
        source_type=ContextSourceType.IMPORTED,
        importance=ContextImportance.HIGH,
        tags=["memory"],
        status=status,
        quality_score=100,
        warnings=[],
        restore_prompt=None,
        context_metadata=metadata,
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )
    chunk = ContextChunkRecord(
        id=f"chunk-{context_id}-{chunk_suffix}",
        context_id=context_id,
        chunk_index=int(chunk_suffix),
        heading=f"Heading {chunk_suffix}",
        content=content,
        token_count=len(content),
        content_hash=f"hash-{context_id}-{chunk_suffix}",
        chunk_metadata=ContextMetadataPayload(),
        created_at=NOW,
    )
    return ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=score,
        fts_score=fts_score,
        vector_score=vector_score,
        why_retrieved="Matched the requested memory.",
    )


@pytest.mark.parametrize(
    ("fts_score", "vector_score", "expected_strategy"),
    [
        (1.0, None, RagStrategy.FTS_ONLY),
        (None, 0.8, RagStrategy.VECTOR_ONLY),
        (0.7, 0.8, RagStrategy.HYBRID),
    ],
)
def test_search_match_payload_exposes_recall_metadata(
    fts_score: float | None,
    vector_score: float | None,
    expected_strategy: RagStrategy,
) -> None:
    match = _match(
        "ctx-metadata",
        fts_score=fts_score,
        vector_score=vector_score,
    )

    payload = match_payload(match)
    response = ContextSearchMatchResponse.model_validate(payload)

    assert response.canonical_context_id == "ctx-metadata"
    assert response.lifecycle_status == "SAVED"
    assert response.source == "context_vault"
    assert response.retrieval_strategy == expected_strategy.value


def test_obsidian_match_exposes_canonical_lifecycle_and_retrieval_source() -> None:
    match = _match(
        "obsidian:ctx-canonical",
        lifecycle_status="current",
        retrieval_source="obsidian_vault",
        canonical_context_id="ctx-canonical",
        source_agent="codex",
    )

    response = ContextSearchMatchResponse.model_validate(match_payload(match))

    assert response.canonical_context_id == "ctx-canonical"
    assert response.lifecycle_status == "CURRENT"
    assert response.source == "obsidian_vault"
    assert response.context.source_agent == "codex"


def test_context_pack_groups_scopes_deduplicates_and_excludes_non_recallable() -> None:
    matches = [
        _match("ctx-project", scope=ContextScope.PROJECT, score=0.9),
        _match("ctx-agent", scope=ContextScope.AGENT, score=0.8),
        _match(
            "ctx-session",
            scope=ContextScope.SESSION,
            score=0.7,
            evidence_refs=["context://decision-001"],
        ),
        _match(
            "ctx-project",
            scope=ContextScope.PROJECT,
            score=0.1,
            content="lower-ranked duplicate",
            chunk_suffix="2",
        ),
        _match(
            "ctx-pending",
            status=ContextStorageStatus.PENDING_REVIEW,
            content="must not be recalled",
        ),
        _match(
            "ctx-superseded",
            lifecycle_status="superseded",
            content="superseded content must stay outside the pack",
        ),
    ]

    context_pack = build_context_pack(query="scope recall", matches=matches)

    assert context_pack.index("## Project Context") < context_pack.index(
        "## Agent Context"
    )
    assert context_pack.index("## Agent Context") < context_pack.index(
        "## Session Context"
    )
    assert context_pack.index("## Session Context") < context_pack.index(
        "## Evidence References"
    )
    assert context_pack.count("- context_id: ctx-project") == 1
    assert "lower-ranked duplicate" not in context_pack
    assert "ctx-pending" not in context_pack
    assert "ctx-superseded" not in context_pack
    assert "artifact://test-results.json" in context_pack
    assert "context://decision-001" in context_pack
    assert "- canonical_context_id: ctx-project" in context_pack
    assert "- lifecycle_status: SAVED" in context_pack
    assert "- retrieval_source: context_vault" in context_pack
    assert "- retrieval_strategy: FTS_ONLY" in context_pack
    assert "- source_actor_id: Hermes" in context_pack


def test_context_pack_limits_rendered_contexts_and_total_characters() -> None:
    matches = [
        _match(
            f"ctx-{index}",
            score=float(20 - index),
            content=f"content-{index}-" + ("x" * 5_000),
        )
        for index in range(12)
    ]

    context_pack = build_context_pack(query="bounded recall", matches=matches)

    assert context_pack.count("- context_id:") == 10
    assert "- context_id: ctx-10\n" not in context_pack
    assert "- context_id: ctx-11\n" not in context_pack
    assert len(context_pack) <= MAX_CONTEXT_PACK_CHARACTERS
    assert "## Evidence References" in context_pack


def test_pack_payload_preserves_raw_matches_when_context_pack_is_bounded() -> None:
    matches = [_match(f"ctx-{index}", score=float(12 - index)) for index in range(12)]
    pack = ContextPack(
        query="raw recall",
        strategy=RagStrategy.HYBRID,
        effective_strategy=RagStrategy.HYBRID,
        warnings=[],
        recall_scopes=[ContextScope.PROJECT],
        matches=matches,
        context_pack=build_context_pack(query="raw recall", matches=matches),
    )

    payload = pack_payload(pack)

    assert len(payload["matches"]) == 12
    assert payload["context_pack"].count("- context_id:") == 10
