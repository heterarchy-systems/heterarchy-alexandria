"""Pure policy tests for functional-memory soft preference."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.application.retrieval.planning.context_memory_function_preference import (
    prefer_memory_function_matches,
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
    MemoryFunction,
)

NOW = datetime(2026, 8, 25, tzinfo=UTC)


def _match(
    context_id: str,
    memory_function: MemoryFunction | None,
    score: float,
) -> ContextSearchMatch:
    """Build one minimal deterministic retrieval match for preference policy tests."""
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
        context_metadata={},
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
        memory_function=memory_function,
    )
    chunk = ContextChunkRecord(
        id=f"chunk-{context_id}",
        context_id=context_id,
        chunk_index=0,
        heading=None,
        content=context_id,
        token_count=1,
        content_hash="a" * 64,
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


def test_empty_memory_function_preference_preserves_ranking() -> None:
    """Absent soft preference must be behaviorally identical to primary ranking."""
    matches = [
        _match("factual", MemoryFunction.FACTUAL, 0.9),
        _match("procedural", MemoryFunction.PROCEDURAL, 0.8),
    ]

    ranked = prefer_memory_function_matches(matches, ())

    assert ranked == matches


def test_memory_function_preference_is_stable_and_score_preserving() -> None:
    """Preference may reorder roles but never drop matches or mutate retrieval scores."""
    matches = [
        _match("factual-1", MemoryFunction.FACTUAL, 0.95),
        _match("procedural-1", MemoryFunction.PROCEDURAL, 0.90),
        _match("experiential-1", MemoryFunction.EXPERIENTIAL, 0.85),
        _match("procedural-2", MemoryFunction.PROCEDURAL, 0.80),
        _match("unclassified", None, 0.75),
        _match("experiential-2", MemoryFunction.EXPERIENTIAL, 0.70),
    ]
    original_scores = {match.context.id: match.score for match in matches}

    ranked = prefer_memory_function_matches(
        matches,
        (MemoryFunction.EXPERIENTIAL, MemoryFunction.PROCEDURAL),
    )

    assert [match.context.id for match in ranked] == [
        "experiential-1",
        "experiential-2",
        "procedural-1",
        "procedural-2",
        "factual-1",
        "unclassified",
    ]
    assert {match.context.id for match in ranked} == set(original_scores)
    assert {match.context.id: match.score for match in ranked} == original_scores
