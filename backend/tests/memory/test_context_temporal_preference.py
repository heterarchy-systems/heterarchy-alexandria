"""Deterministic current-state preference tests for adaptive Context retrieval."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.application.retrieval.planning.context_retrieval_plan_resolution import (
    resolve_context_retrieval_execution,
)
from app.memory.application.retrieval.planning.context_temporal_preference import (
    prefer_current_temporal_matches,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
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

NOW = datetime(2026, 8, 25, tzinfo=UTC)


def _match(
    context_id: str,
    score: float,
    temporal_metadata: ContextMetadataPayload | None = None,
) -> ContextSearchMatch:
    context = ContextRecord(
        id=context_id,
        kind=ContextKind.MEMORY,
        title=context_id,
        summary=context_id,
        content=context_id,
        content_format=ContextContentFormat.MARKDOWN,
        project="heterarchy-alexandria",
        scope=ContextScope.PROJECT,
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="test",
        source_type=ContextSourceType.SYSTEM,
        importance=ContextImportance.MEDIUM,
        tags=(),
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=(),
        restore_prompt=None,
        context_metadata={} if temporal_metadata is None else temporal_metadata,
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )
    chunk = ContextChunkRecord(
        id=f"chunk:{context_id}",
        context_id=context_id,
        chunk_index=0,
        heading=context_id,
        content=context_id,
        token_count=1,
        content_hash=context_id,
        chunk_metadata={},
        created_at=NOW,
    )
    return ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=score,
        fts_score=score,
        vector_score=None,
        why_retrieved="test",
    )


def test_temporal_preference_reorders_only_by_explicit_canonical_time() -> None:
    """Current-state preference should use semantic timestamps and preserve scores/membership."""
    old = _match("old", 0.95, {"valid_from": "2026-08-20T00:00:00+00:00"})
    undated = _match("undated", 0.90)
    new = _match("new", 0.80, {"observed_at": "2026-08-24T00:00:00+00:00"})

    reordered = prefer_current_temporal_matches([old, undated, new], True)

    assert [match.context.id for match in reordered] == ["new", "old", "undated"]
    assert {match.context.id for match in reordered} == {"old", "undated", "new"}
    assert {match.context.id: match.score for match in reordered} == {
        "old": 0.95,
        "undated": 0.90,
        "new": 0.80,
    }


def test_temporal_preference_is_stable_for_equal_or_invalid_metadata() -> None:
    """Equal, naive, or malformed timestamps must not introduce unstable ranking changes."""
    same_a = _match("same-a", 0.9, {"recorded_at": "2026-08-24T00:00:00+00:00"})
    same_b = _match("same-b", 0.8, {"recorded_at": "2026-08-24T00:00:00+00:00"})
    naive = _match("naive", 0.7, {"recorded_at": "2026-08-25T00:00:00"})
    invalid = _match("invalid", 0.6, {"valid_from": "not-a-timestamp"})

    reordered = prefer_current_temporal_matches([same_a, same_b, naive, invalid], True)

    assert [match.context.id for match in reordered] == [
        "same-a",
        "same-b",
        "naive",
        "invalid",
    ]


def test_temporal_preference_is_disabled_for_fixed_strategy_and_enabled_for_auto() -> (
    None
):
    """Fixed strategy behavior must remain unchanged while AUTO temporal intent enables preference."""
    fixed = resolve_context_retrieval_execution(
        "지금 최종 상태를 찾아줘",
        RagStrategy.HYBRID,
        5,
        None,
    )
    adaptive = resolve_context_retrieval_execution(
        "지금 최종 상태를 찾아줘",
        RagStrategy.AUTO,
        5,
        None,
    )

    assert fixed.temporal_current_preference is False
    assert fixed.adaptive_plan is None
    assert adaptive.temporal_current_preference is True
    assert adaptive.adaptive_plan is not None
