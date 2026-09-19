"""Budget-contract tests for the delivery brief builder."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.memory.application.retrieval.context_brief import (
    MAX_CONTEXT_BRIEF_TOTAL_SERIALIZATION_BYTES,
    build_context_brief,
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
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextBriefBudgetError,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _match(context_id: str, *, score: float, content: str) -> ContextSearchMatch:
    """Build one retrieval match for the brief builder.

    Args:
        context_id: Context identifier.
        score: Retrieval score.
        content: Chunk content.

    Returns:
        Context search match read model.
    """
    context = ContextRecord(
        id=context_id,
        kind=ContextKind.HANDOFF,
        title=f"Context {context_id}",
        summary="summary",
        content=content,
        content_format=ContextContentFormat.MARKDOWN,
        project="heterarchy-alexandria",
        scope=ContextScope.PROJECT,
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="Hermes",
        source_type=ContextSourceType.AGENT,
        importance=ContextImportance.HIGH,
        tags=[],
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=[],
        restore_prompt=None,
        context_metadata=ContextMetadataPayload(),
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )
    chunk = ContextChunkRecord(
        id=f"chunk-{context_id}-1",
        context_id=context_id,
        chunk_index=1,
        heading=None,
        content=content,
        token_count=len(content.split()),
        content_hash=content.encode("utf-8").hex()[:64],
        chunk_metadata=ContextMetadataPayload(),
        created_at=NOW,
    )
    return ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=score,
        fts_score=score,
        vector_score=None,
        why_retrieved="test match",
    )


def test_tiny_budget_that_cannot_deliver_any_entry_raises_typed_error() -> None:
    """A budget too small for one entry must fail typed, not return empty."""
    match = _match("ctx-tiny", score=1.0, content="## Goal\nShip the brief.\n")

    with pytest.raises(MemoryContextBriefBudgetError) as excinfo:
        build_context_brief(query="tiny", matches=[match], byte_budget=32)

    assert "byte_budget=32" in str(excinfo.value)


def test_zero_record_budget_with_candidates_raises_typed_error() -> None:
    """A record budget of zero with deliverable candidates must fail typed."""
    match = _match("ctx-zero", score=1.0, content="## Goal\nShip the brief.\n")

    with pytest.raises(MemoryContextBriefBudgetError):
        build_context_brief(query="zero", matches=[match], record_budget=0)


def test_absent_matches_stay_a_legitimate_empty_delivery() -> None:
    """No matches means nothing to deliver: the empty brief stays a success."""
    payload = build_context_brief(query="empty", matches=[], byte_budget=32)

    assert payload["entries"] == []
    assert payload["omitted"] == []


def test_suppressed_unchanged_entries_stay_a_legitimate_empty_delivery() -> None:
    """Already-delivered suppression without new candidates must not error."""
    content = "## Goal\nunchanged body\n"
    match = _match("ctx-same", score=1.0, content=content)

    payload = build_context_brief(
        query="replay",
        matches=[match],
        byte_budget=64,
        previously_delivered=[("ctx-same", match.chunk.content_hash)],
    )

    assert payload["entries"] == []
    assert [marker["context_id"] for marker in payload["already_delivered"]] == [
        "ctx-same"
    ]
    assert payload["omitted"] == []


def test_total_serialization_payload_cap_is_enforced() -> None:
    """A payload whose omission metadata exceeds the total cap fails typed."""
    section_count = 2400
    content = "\n".join(
        f"## Section {index}\nbody {index}\n" for index in range(section_count)
    )
    match = _match("ctx-huge", score=1.0, content=content)

    with pytest.raises(MemoryContextBriefBudgetError) as excinfo:
        build_context_brief(
            query="cap",
            matches=[match],
            byte_budget=2_000,
            record_budget=1,
        )

    assert f"{MAX_CONTEXT_BRIEF_TOTAL_SERIALIZATION_BYTES} bytes" in str(excinfo.value)
