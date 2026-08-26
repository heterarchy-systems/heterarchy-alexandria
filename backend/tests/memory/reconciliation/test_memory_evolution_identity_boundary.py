"""Pure isolation tests for Phase 7 reconciliation candidate identity boundaries."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.application.reconciliation.candidates.memory_candidate_recall_service import (
    _matches_candidate_identity,
    recall_candidate_from_match,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextGraphEvidence,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemoryTemporalState,
)
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextGraphDirection,
    ContextGraphSignalType,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
)

NOW = datetime(2026, 8, 25, tzinfo=UTC)


def _candidate(
    project: str | None = "heterarchy-alexandria",
    agent_id: str | None = None,
    scope: ContextScope = ContextScope.PROJECT,
) -> MemoryCandidate:
    """Build one deterministic memory proposal for identity-boundary tests."""
    return MemoryCandidate(
        candidate_id="candidate-1",
        title="Storage decision",
        body="Canonical storage decision.",
        canonical_claims=(),
        scope=scope,
        project=project,
        tags=(),
        source_refs=(),
        recorded_at=NOW,
        observed_at=None,
        valid_from=None,
        valid_to=None,
        requested_lifecycle="active",
        content_hash="a" * 64,
        agent_id=agent_id,
    )


def _context(
    context_id: str,
    project: str | None = "heterarchy-alexandria",
    agent_id: str | None = None,
    scope: ContextScope = ContextScope.PROJECT,
) -> ContextRecord:
    """Build one Context read model with an explicit reconciliation identity."""
    return ContextRecord(
        id=context_id,
        kind=ContextKind.MEMORY,
        title=context_id,
        summary=context_id,
        content=context_id,
        content_format=ContextContentFormat.MARKDOWN,
        project=project,
        scope=scope,
        workspace_id=None,
        agent_id=agent_id,
        user_id=None,
        session_id=None,
        visibility=scope,
        source_agent="test",
        source_type=ContextSourceType.SYSTEM,
        importance=ContextImportance.MEDIUM,
        tags=(),
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=(),
        restore_prompt=None,
        context_metadata={"content_hash": "b" * 64},
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )


def test_cross_project_context_cannot_enter_reconciliation_policy() -> None:
    """Semantically similar memory from another project must be rejected before policy."""
    candidate = _candidate(project="heterarchy-alexandria")

    assert _matches_candidate_identity(
        _context("same-project", project="heterarchy-alexandria"), candidate
    )
    assert not _matches_candidate_identity(
        _context("other-project", project="heterarchy-orchestration"), candidate
    )


def test_cross_scope_and_owner_contexts_are_rejected() -> None:
    """Agent-owned proposals must not reconcile against another owner or scope."""
    candidate = _candidate(project=None, agent_id="agent-a", scope=ContextScope.AGENT)

    assert _matches_candidate_identity(
        _context(
            "same-agent", project=None, agent_id="agent-a", scope=ContextScope.AGENT
        ),
        candidate,
    )
    assert not _matches_candidate_identity(
        _context(
            "other-agent", project=None, agent_id="agent-b", scope=ContextScope.AGENT
        ),
        candidate,
    )
    assert not _matches_candidate_identity(
        _context("global", project=None, agent_id=None, scope=ContextScope.GLOBAL),
        candidate,
    )


def test_recall_candidate_derives_trusted_graph_neighbors_and_ancestor_lineage() -> (
    None
):
    """Graph counterparts and supersedes ancestry must feed Rust features directionally."""
    context = _context("ctx-current")
    chunk = ContextChunkRecord(
        id="chunk-current",
        context_id=context.id,
        chunk_index=0,
        heading=None,
        content=context.content,
        token_count=1,
        content_hash="c" * 64,
        chunk_metadata={},
        created_at=NOW,
    )
    match = ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=1.0,
        fts_score=1.0,
        vector_score=None,
        why_retrieved="test",
        graph_evidence=(
            ContextGraphEvidence(
                signal=ContextGraphSignalType.GRAPH_PROXIMITY,
                relation="wikilink",
                direction=ContextGraphDirection.OUTGOING,
                source_context_id=context.id,
                target_context_id="ctx-neighbor-b",
                target_title="Neighbor B",
                distance=1,
                evidence_ref="graph://ctx-current/wikilink/ctx-neighbor-b",
            ),
            ContextGraphEvidence(
                signal=ContextGraphSignalType.GRAPH_PROXIMITY,
                relation="wikilink",
                direction=ContextGraphDirection.INCOMING,
                source_context_id="ctx-neighbor-a",
                target_context_id=context.id,
                target_title=context.title,
                distance=1,
                evidence_ref="graph://ctx-neighbor-a/wikilink/ctx-current",
            ),
            ContextGraphEvidence(
                signal=ContextGraphSignalType.GRAPH_PROXIMITY,
                relation="wikilink",
                direction=ContextGraphDirection.OUTGOING,
                source_context_id=context.id,
                target_context_id="ctx-neighbor-b",
                target_title="Neighbor B",
                distance=1,
                evidence_ref="graph://duplicate",
            ),
        ),
    )
    temporal = MemoryTemporalState(
        context_id=context.id,
        recorded_at=NOW,
        observed_at=None,
        valid_from=NOW,
        valid_to=None,
        is_current=True,
        superseded_by=("ctx-newer",),
        supersedes=("ctx-old-b", "ctx-old-a", "ctx-old-a"),
    )

    recalled = recall_candidate_from_match(
        match,
        temporal_state=temporal,
        candidate_hash="d" * 64,
    )

    assert recalled.graph_neighbors == ("ctx-neighbor-a", "ctx-neighbor-b")
    assert recalled.lineage_ancestors == ("ctx-old-a", "ctx-old-b")
    assert "ctx-newer" not in recalled.lineage_ancestors
