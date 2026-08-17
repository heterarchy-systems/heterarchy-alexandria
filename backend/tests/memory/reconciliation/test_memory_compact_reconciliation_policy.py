"""Tests for reconciliation-aware Memory Compact fact classification and safety."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.application.reconciliation.memory_compact_reconciliation_policy import (
    MemoryCompactReconciliationPolicy,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCompactFact,
    MemoryCompactFactBuckets,
    MemoryTemporalRecallMatch,
    MemoryTemporalRecallPack,
    MemoryTemporalState,
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
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryCompactFactCategory,
    MemoryCompactSafetyIssue,
    MemoryTemporalRecallMode,
)

JULY_1 = datetime(2026, 7, 1, tzinfo=UTC)
JULY_20 = datetime(2026, 7, 20, tzinfo=UTC)
JULY_25 = datetime(2026, 7, 25, tzinfo=UTC)


def _context(
    context_id: str,
    title: str,
    content: str,
    *,
    evidence: bool = True,
) -> ContextRecord:
    return ContextRecord(
        id=context_id,
        kind=ContextKind.MEMORY,
        title=title,
        summary=title,
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
        tags=["memory"],
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=[],
        restore_prompt=None,
        context_metadata=(
            {"evidence_refs": [f"Evidence/{context_id}.md"]} if evidence else {}
        ),
        created_at=JULY_1,
        updated_at=JULY_25,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )


def _recall_match(
    context: ContextRecord,
    *,
    state: MemoryTemporalState | None,
    is_current: bool,
    conflict_set_ids: tuple[str, ...] = (),
    superseded_by: tuple[str, ...] = (),
    relation_summary: tuple[str, ...] = (),
) -> MemoryTemporalRecallMatch:
    match = ContextSearchMatch(
        context=context,
        chunk=ContextChunkRecord(
            id=f"chunk:{context.id}",
            context_id=context.id,
            chunk_index=0,
            heading="Memory",
            content=context.content,
            token_count=5,
            content_hash=f"hash:{context.id}",
            chunk_metadata={},
            created_at=JULY_1,
        ),
        score=1.0,
        fts_score=1.0,
        vector_score=1.0,
        why_retrieved="memory compact input",
    )
    return MemoryTemporalRecallMatch(
        match=match,
        temporal_state=state,
        is_current=is_current,
        conflict_set_ids=conflict_set_ids,
        superseded_by=superseded_by,
        relation_summary=relation_summary,
    )


def _state(
    context_id: str,
    *,
    is_current: bool,
    valid_to: datetime | None = None,
    conflict_set_ids: tuple[str, ...] = (),
    superseded_by: tuple[str, ...] = (),
    relation_summary: tuple[str, ...] = (),
) -> MemoryTemporalState:
    return MemoryTemporalState(
        context_id=context_id,
        recorded_at=JULY_25,
        observed_at=JULY_1,
        valid_from=JULY_1,
        valid_to=valid_to,
        is_current=is_current,
        conflict_set_ids=conflict_set_ids,
        superseded_by=superseded_by,
        relation_summary=relation_summary,
    )


def test_policy_separates_all_five_fact_categories_without_collapsing() -> None:
    current = _context("obsidian:current", "Current", "Current fact.")
    historical = _context("obsidian:historical", "Historical", "Historical fact.")
    conflict = _context("obsidian:conflict", "Conflict", "Conflicting fact.")
    uncertain = _context("obsidian:uncertain", "Uncertain", "Uncertain fact.")
    superseded = _context("obsidian:superseded", "Superseded", "Superseded fact.")
    pack = MemoryTemporalRecallPack(
        query="memory compact",
        mode=MemoryTemporalRecallMode.ALL,
        as_of=None,
        strategy=RagStrategy.HYBRID,
        effective_strategy=RagStrategy.HYBRID,
        warnings=(),
        recall_scopes=(ContextScope.PROJECT,),
        matches=(
            _recall_match(
                current,
                state=_state(current.id, is_current=True),
                is_current=True,
            ),
            _recall_match(
                historical,
                state=_state(
                    historical.id,
                    is_current=False,
                    valid_to=JULY_20,
                ),
                is_current=False,
            ),
            _recall_match(
                conflict,
                state=_state(
                    conflict.id,
                    is_current=True,
                    conflict_set_ids=("conflict-1",),
                ),
                is_current=True,
                conflict_set_ids=("conflict-1",),
                relation_summary=("contradicts:obsidian:current",),
            ),
            _recall_match(
                uncertain,
                state=None,
                is_current=True,
            ),
            _recall_match(
                superseded,
                state=_state(
                    superseded.id,
                    is_current=False,
                    valid_to=JULY_20,
                    superseded_by=("obsidian:current",),
                ),
                is_current=False,
                superseded_by=("obsidian:current",),
                relation_summary=("superseded_by:obsidian:current",),
            ),
        ),
        context_pack="raw temporal pack",
    )

    review = MemoryCompactReconciliationPolicy().prepare(pack)

    assert [fact.context_id for fact in review.buckets.current_facts] == [
        "obsidian:current"
    ]
    assert [fact.context_id for fact in review.buckets.historical_facts] == [
        "obsidian:historical"
    ]
    assert [fact.context_id for fact in review.buckets.open_conflicts] == [
        "obsidian:conflict"
    ]
    assert [fact.context_id for fact in review.buckets.uncertain_claims] == [
        "obsidian:uncertain"
    ]
    assert [fact.context_id for fact in review.buckets.superseded_facts] == [
        "obsidian:superseded"
    ]
    assert review.safe_to_publish is True
    assert review.issues == ()
    assert len(review.warnings) == 3
    assert "## Current Facts" in review.rendered_markdown
    assert "## Historical Facts" in review.rendered_markdown
    assert "## Open Conflicts" in review.rendered_markdown
    assert "## Uncertain Claims" in review.rendered_markdown
    assert "## Superseded Facts" in review.rendered_markdown
    assert "Conflict sets: conflict-1" in review.rendered_markdown


def _fact(
    context_id: str,
    category: MemoryCompactFactCategory,
    *,
    content: str,
    evidence_refs: tuple[str, ...] = ("Evidence/source.md",),
    conflict_set_ids: tuple[str, ...] = (),
    relation_summary: tuple[str, ...] = (),
) -> MemoryCompactFact:
    return MemoryCompactFact(
        context_id=context_id,
        title=context_id,
        content=content,
        category=category,
        valid_from=JULY_1,
        valid_to=None,
        evidence_refs=evidence_refs,
        conflict_set_ids=conflict_set_ids,
        relation_summary=relation_summary,
    )


def test_review_detects_all_five_compact_safety_defects() -> None:
    duplicate_content = "The same claim appears twice."
    buckets = MemoryCompactFactBuckets(
        current_facts=(
            _fact(
                "obsidian:state-collapse",
                MemoryCompactFactCategory.CURRENT,
                content=duplicate_content,
                evidence_refs=(),
                conflict_set_ids=("conflict-leak",),
                relation_summary=("superseded_by:obsidian:new",),
            ),
            _fact(
                "obsidian:duplicate-current",
                MemoryCompactFactCategory.CURRENT,
                content=duplicate_content,
            ),
        ),
        historical_facts=(
            _fact(
                "obsidian:state-collapse",
                MemoryCompactFactCategory.HISTORICAL,
                content="Historical form of the same Context.",
            ),
        ),
    )

    review = MemoryCompactReconciliationPolicy().review(buckets)

    assert set(review.issues) == {
        MemoryCompactSafetyIssue.UNRESOLVED_CONTRADICTION_LEAKAGE,
        MemoryCompactSafetyIssue.TEMPORAL_STATE_COLLAPSE,
        MemoryCompactSafetyIssue.SUPERSEDED_FACT_PRESENTED_AS_CURRENT,
        MemoryCompactSafetyIssue.UNSUPPORTED_MERGE,
        MemoryCompactSafetyIssue.DUPLICATE_CLAIM_INFLATION,
    }
    assert review.safe_to_publish is False
