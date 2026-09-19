"""Contract tests for recall metadata and bounded Context Packs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_type_hints

import pytest

from app.memory.application.retrieval.context_brief import build_context_brief
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
from app.memory.domain.types.context_payload_types import (
    ContextBriefPayload,
    ContextMetadataPayload,
)
from app.memory.interface.schemas.context.context_mapping import (
    match_payload,
    pack_payload,
)
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextBriefResponse,
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
    graph_score: float | None = None,
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
        graph_score=graph_score,
        why_retrieved="Matched the requested memory.",
    )


@pytest.mark.parametrize(
    ("fts_score", "vector_score", "graph_score", "expected_strategy"),
    [
        (1.0, None, None, RagStrategy.FTS_ONLY),
        (None, 0.8, None, RagStrategy.VECTOR_ONLY),
        (0.7, 0.8, None, RagStrategy.HYBRID),
        (None, None, 0.9, RagStrategy.AUTO),
        (0.7, 0.8, 0.9, RagStrategy.AUTO),
    ],
)
def test_search_match_payload_exposes_recall_metadata(
    fts_score: float | None,
    vector_score: float | None,
    graph_score: float | None,
    expected_strategy: RagStrategy,
) -> None:
    match = _match(
        "ctx-metadata",
        fts_score=fts_score,
        vector_score=vector_score,
        graph_score=graph_score,
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


_BRIEF_CORE_CONTENT = (
    "# Handoff\n"
    "\n"
    "## Goal\n"
    "Ship the budgeted context brief.\n"
    "\n"
    "## Constraints\n"
    "Stay inside the delivery byte budget.\n"
    "\n"
    "## Unconfirmed Status\n"
    "Cache eviction behavior is unverified.\n"
    "\n"
    "## Next Actions\n"
    "Land the contract tests.\n"
    "\n"
    "## Summary\n"
    "Supplementary narrative that may be trimmed under budget pressure."
)


def test_context_brief_respects_byte_budget_preserves_core_and_reports_omissions() -> (
    None
):
    matches = [
        _match("ctx-core", score=0.9, content=_BRIEF_CORE_CONTENT),
        _match(
            "ctx-overflow",
            score=0.5,
            content=_BRIEF_CORE_CONTENT,
            chunk_suffix="2",
        ),
    ]

    payload = build_context_brief(
        query="brief recall",
        matches=matches,
        byte_budget=2_000,
        record_budget=1,
    )
    response = ContextBriefResponse.model_validate(payload)

    assert len(payload["context_brief"].encode("utf-8")) == payload["total_bytes"]
    assert payload["total_bytes"] <= 2_000
    brief = payload["context_brief"]
    assert "Ship the budgeted context brief." in brief
    assert "Stay inside the delivery byte budget." in brief
    assert "Cache eviction behavior is unverified." in brief
    assert "Land the contract tests." in brief
    assert [entry["context_id"] for entry in payload["entries"]] == ["ctx-core"]
    assert response.entries[0].delivery_status == "new"
    overflow_omissions = [
        record
        for record in payload["omitted"]
        if record["context_id"] == "ctx-overflow"
    ]
    assert len(overflow_omissions) == 1
    assert overflow_omissions[0]["reason"] == "record_budget"
    refetch = overflow_omissions[0]["refetch"]
    assert refetch["query"] == "brief recall"
    assert refetch["context_id"] == "ctx-overflow"
    assert refetch["canonical_context_id"] == "ctx-overflow"
    assert refetch["chunk_id"] == "chunk-ctx-overflow-2"
    assert "artifact://test-results.json" in refetch["evidence_refs"]
    assert response.omitted[0].refetch.retrieval_strategy == "FTS_ONLY"


def test_context_brief_suppresses_unchanged_entries_and_flags_changed_delivery() -> (
    None
):
    unchanged = _match("ctx-same", score=0.9, content="## Goal\n" + ("u" * 400))
    changed = _match("ctx-changed", score=0.8, content="## Goal\n" + ("c" * 400))
    first = build_context_brief(query="suppress", matches=[unchanged, changed])
    assert [entry["context_id"] for entry in first["entries"]] == [
        "ctx-same",
        "ctx-changed",
    ]

    second = build_context_brief(
        query="suppress",
        matches=[unchanged, changed],
        previously_delivered=[
            ("ctx-same", unchanged.chunk.content_hash),
            ("ctx-changed", changed.chunk.content_hash),
        ],
    )

    assert second["entries"] == []
    assert [marker["context_id"] for marker in second["already_delivered"]] == [
        "ctx-same",
        "ctx-changed",
    ]
    assert second["already_delivered"][0]["content_hash"] == (
        unchanged.chunk.content_hash
    )
    assert second["already_delivered"][0]["refetch"]["context_id"] == "ctx-same"
    assert second["already_delivered"][0]["refetch"]["query"] == "suppress"
    assert second["total_bytes"] < first["total_bytes"]

    changed_updated = _match(
        "ctx-changed",
        score=0.8,
        content="## Goal\n" + ("n" * 400),
        chunk_suffix="2",
    )
    third = build_context_brief(
        query="suppress",
        matches=[unchanged, changed_updated],
        previously_delivered=[
            ("ctx-same", unchanged.chunk.content_hash),
            ("ctx-changed", changed.chunk.content_hash),
        ],
    )

    assert [entry["context_id"] for entry in third["entries"]] == ["ctx-changed"]
    assert third["entries"][0]["delivery_status"] == "changed"
    assert third["entries"][0]["content_hash"] == changed_updated.chunk.content_hash
    assert [marker["context_id"] for marker in third["already_delivered"]] == [
        "ctx-same",
    ]


def test_context_brief_marks_truncated_sections_with_delivered_bytes_and_refetch() -> (
    None
):
    goal_body = "g" * 800
    content = f"## Goal\n{goal_body}\n\n## Constraints\nStay small."
    match = _match("ctx-trunc", score=1.0, content=content)

    payload = build_context_brief(query="truncate", matches=[match], byte_budget=500)

    entry = payload["entries"][0]
    truncated = [section for section in entry["sections"] if section["truncated"]]
    assert len(truncated) == 1
    section = truncated[0]
    assert section["heading"] == "Goal"
    assert section["delivered_bytes"] == len(section["text"].encode("utf-8"))
    assert section["delivered_bytes"] < len(goal_body.encode("utf-8"))
    assert goal_body not in payload["context_brief"]
    assert payload["total_bytes"] <= 500
    truncation_omissions = [
        record
        for record in payload["omitted"]
        if record["reason"] == "section_truncated"
    ]
    assert len(truncation_omissions) == 1
    assert truncation_omissions[0]["context_id"] == "ctx-trunc"
    assert truncation_omissions[0]["heading"] == "Goal"
    assert truncation_omissions[0]["refetch"]["query"] == "truncate"
    assert truncation_omissions[0]["refetch"]["chunk_id"] == "chunk-ctx-trunc-1"


def test_context_brief_output_type_prevents_self_amplification() -> None:
    brief = build_context_brief(query="guard", matches=[_match("ctx-guard")])

    identity_keys = {"id", "context_id", "canonical_context_id", "context"}
    assert not set(brief) & identity_keys
    match_keys = {
        "context",
        "chunk",
        "score",
        "fts_score",
        "vector_score",
        "graph_score",
        "why_retrieved",
        "graph_evidence",
    }
    assert not set(brief) & match_keys
    entry_identity_keys = {"id", "canonical_context_id", "context"}
    for entry in brief["entries"]:
        assert not set(entry) & entry_identity_keys
        assert "context" not in entry

    hints = get_type_hints(build_context_brief)
    assert hints["matches"] == list[ContextSearchMatch]
    assert hints["return"] == ContextBriefPayload
    # Structure prevents re-feeding a brief as retrieval evidence: the input
    # type is the ContextSearchMatch read model, never a brief payload, so
    # generating a brief from a brief-shaped input is a static type error
    # (enforced by pyrefly) and brief-derived content cannot grow the pack.


def test_context_brief_reports_exact_bytes_and_labeled_token_estimate() -> None:
    content = "## Goal\n요약 예산 유지: 한글 본문.\n\n## Next Actions\n브리프 검증."
    match = _match("ctx-bytes", score=1.0, content=content)

    payload = build_context_brief(query="예산", matches=[match])

    brief_text = payload["context_brief"]
    assert payload["total_bytes"] == len(brief_text.encode("utf-8"))
    assert payload["total_bytes"] > len(brief_text)
    assert payload["estimated_tokens"] == len(brief_text) // 4
    description = ContextBriefResponse.model_fields["estimated_tokens"].description
    assert description is not None
    assert "estimate" in description.lower()


def test_context_brief_handles_absent_matches_with_unspent_budget() -> None:
    payload = build_context_brief(query="empty recall", matches=[])

    response = ContextBriefResponse.model_validate(payload)

    assert payload["entries"] == []
    assert payload["already_delivered"] == []
    assert payload["omitted"] == []
    assert payload["total_bytes"] == len(payload["context_brief"].encode("utf-8"))
    assert payload["total_bytes"] < payload["byte_budget"]
    assert payload["estimated_tokens"] == len(payload["context_brief"]) // 4
    assert payload["context_brief"].startswith("# Alexandria Context Brief")
    assert response.total_bytes == payload["total_bytes"]
