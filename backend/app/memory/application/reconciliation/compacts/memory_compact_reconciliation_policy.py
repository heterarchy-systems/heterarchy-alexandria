"""Reconciliation-aware Memory Compact fact classification and safety review."""

from __future__ import annotations

from datetime import datetime

from app.memory.domain.entities.memory_reconciliation import (
    MemoryCompactFact,
    MemoryCompactFactBuckets,
    MemoryCompactSafetyReview,
    MemoryTemporalRecallMatch,
    MemoryTemporalRecallPack,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryCompactFactCategory,
    MemoryCompactSafetyIssue,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.shared.types.extra_types import JSONValue


class MemoryCompactReconciliationPolicy:
    """Prevent conflicts and temporal states from being collapsed into one fact."""

    def prepare(
        self,
        pack: MemoryTemporalRecallPack,
    ) -> MemoryCompactSafetyReview:
        """Classify recalled Contexts and review the resulting structured fact input.

        Args:
            pack: Pack.

        Returns:
            MemoryCompactSafetyReview: Operation result.
        """
        return self.review(_fact_buckets(pack))

    def review(
        self,
        buckets: MemoryCompactFactBuckets,
    ) -> MemoryCompactSafetyReview:
        """Review pre-classified fact buckets before durable Compact publication.

        Args:
            buckets: Buckets.

        Returns:
            MemoryCompactSafetyReview: Operation result.
        """
        issues = _safety_issues(buckets)
        warnings = _safety_warnings(buckets)
        return MemoryCompactSafetyReview(
            buckets=buckets,
            issues=issues,
            safe_to_publish=not issues,
            warnings=warnings,
            rendered_markdown=render_fact_buckets(buckets),
        )


def render_fact_buckets(buckets: MemoryCompactFactBuckets) -> str:
    """Render fact buckets without merging current, historical, or conflict state.

    Args:
        buckets: Buckets.

    Returns:
        str: Operation result.
    """
    sections = (
        ("Current Facts", buckets.current_facts),
        ("Historical Facts", buckets.historical_facts),
        ("Open Conflicts", buckets.open_conflicts),
        ("Uncertain Claims", buckets.uncertain_claims),
        ("Superseded Facts", buckets.superseded_facts),
    )
    rendered: list[str] = []
    for heading, facts in sections:
        rendered.append(f"## {heading}")
        if not facts:
            rendered.append("- None")
            rendered.append("")
            continue
        for fact in facts:
            rendered.append(f"- **{fact.title}** — {fact.content.strip()}")
            if fact.valid_from is not None or fact.valid_to is not None:
                rendered.append(
                    "  - Validity: "
                    f"{_datetime_text(fact.valid_from)} → {_datetime_text(fact.valid_to)}"
                )
            if fact.conflict_set_ids:
                rendered.append(
                    "  - Conflict sets: " + ", ".join(fact.conflict_set_ids)
                )
            if fact.relation_summary:
                rendered.append("  - Relations: " + ", ".join(fact.relation_summary))
        rendered.append("")
    return "\n".join(rendered).rstrip() + "\n"


def _fact_buckets(pack: MemoryTemporalRecallPack) -> MemoryCompactFactBuckets:
    """Execute fact buckets.

    Args:
        pack: Pack used by this operation.

    Returns:
        MemoryCompactFactBuckets result produced by fact buckets.
    """
    categorized: dict[MemoryCompactFactCategory, list[MemoryCompactFact]] = {
        category: [] for category in MemoryCompactFactCategory
    }
    for item in pack.matches:
        category = _fact_category(item)
        categorized[category].append(_fact(item, category=category))
    return MemoryCompactFactBuckets(
        current_facts=tuple(categorized[MemoryCompactFactCategory.CURRENT]),
        historical_facts=tuple(categorized[MemoryCompactFactCategory.HISTORICAL]),
        open_conflicts=tuple(categorized[MemoryCompactFactCategory.OPEN_CONFLICT]),
        uncertain_claims=tuple(categorized[MemoryCompactFactCategory.UNCERTAIN]),
        superseded_facts=tuple(categorized[MemoryCompactFactCategory.SUPERSEDED]),
    )


def _fact_category(item: MemoryTemporalRecallMatch) -> MemoryCompactFactCategory:
    """Execute fact category.

    Args:
        item: Item being processed.

    Returns:
        MemoryCompactFactCategory result produced by fact category.
    """
    if item.conflict_set_ids:
        return MemoryCompactFactCategory.OPEN_CONFLICT
    state = item.temporal_state
    if state is None:
        return MemoryCompactFactCategory.UNCERTAIN
    if item.superseded_by:
        return MemoryCompactFactCategory.SUPERSEDED
    if item.is_current:
        return MemoryCompactFactCategory.CURRENT
    if state.valid_to is not None:
        return MemoryCompactFactCategory.HISTORICAL
    return MemoryCompactFactCategory.UNCERTAIN


def _fact(
    item: MemoryTemporalRecallMatch,
    category: MemoryCompactFactCategory,
) -> MemoryCompactFact:
    """Execute fact.

    Args:
        item: Item being processed.
        category: Category used by this operation.

    Returns:
        MemoryCompactFact result produced by fact.
    """
    context = item.match.context
    state = item.temporal_state
    return MemoryCompactFact(
        context_id=context.id,
        title=context.title,
        content=context.content,
        category=category,
        valid_from=None if state is None else state.valid_from,
        valid_to=None if state is None else state.valid_to,
        evidence_refs=_evidence_refs(context.context_metadata),
        conflict_set_ids=item.conflict_set_ids,
        relation_summary=item.relation_summary,
    )


def _safety_issues(
    buckets: MemoryCompactFactBuckets,
) -> tuple[MemoryCompactSafetyIssue, ...]:
    """Execute safety issues.

    Args:
        buckets: Buckets used by this operation.

    Returns:
        tuple[MemoryCompactSafetyIssue, ...] result produced by safety issues.
    """
    issues: list[MemoryCompactSafetyIssue] = []
    all_facts = _all_facts(buckets)
    context_categories: dict[str, set[MemoryCompactFactCategory]] = {}
    content_contexts: dict[str, set[str]] = {}
    for fact in all_facts:
        context_categories.setdefault(fact.context_id, set()).add(fact.category)
        normalized_content = " ".join(fact.content.casefold().split())
        content_contexts.setdefault(normalized_content, set()).add(fact.context_id)
    if any(len(categories) > 1 for categories in context_categories.values()):
        issues.append(MemoryCompactSafetyIssue.TEMPORAL_STATE_COLLAPSE)
    if any(len(context_ids) > 1 for context_ids in content_contexts.values()):
        issues.append(MemoryCompactSafetyIssue.DUPLICATE_CLAIM_INFLATION)
    if any(not fact.evidence_refs for fact in buckets.current_facts):
        issues.append(MemoryCompactSafetyIssue.UNSUPPORTED_MERGE)
    if _current_temporal_facts(buckets):
        issues.append(MemoryCompactSafetyIssue.SUPERSEDED_FACT_PRESENTED_AS_CURRENT)
    if any(fact.conflict_set_ids for fact in buckets.current_facts):
        issues.append(MemoryCompactSafetyIssue.UNRESOLVED_CONTRADICTION_LEAKAGE)
    return tuple(dict.fromkeys(issues))


def _safety_warnings(
    buckets: MemoryCompactFactBuckets,
) -> tuple[str, ...]:
    """Execute safety warnings.

    Args:
        buckets: Buckets used by this operation.

    Returns:
        tuple[str, ...] result produced by safety warnings.
    """
    warnings: list[str] = []
    if buckets.open_conflicts:
        warnings.append(
            "Open conflicts are isolated and must remain explicitly labeled in the compact."
        )
    if buckets.uncertain_claims:
        warnings.append(
            "Uncertain claims are isolated and must not be rewritten as confirmed facts."
        )
    if buckets.superseded_facts:
        warnings.append(
            "Superseded facts are historical context and must not appear as current state."
        )
    return tuple(warnings)


def _all_facts(buckets: MemoryCompactFactBuckets) -> tuple[MemoryCompactFact, ...]:
    """Execute all facts.

    Args:
        buckets: Buckets used by this operation.

    Returns:
        tuple[MemoryCompactFact, ...] result produced by all facts.
    """
    return (
        *buckets.current_facts,
        *buckets.historical_facts,
        *buckets.open_conflicts,
        *buckets.uncertain_claims,
        *buckets.superseded_facts,
    )


def _current_temporal_facts(
    buckets: MemoryCompactFactBuckets,
) -> tuple[MemoryCompactFact, ...]:
    """Execute current temporal facts.

    Args:
        buckets: Buckets used by this operation.

    Returns:
        tuple[MemoryCompactFact, ...] result produced by current temporal facts.
    """
    return tuple(
        fact
        for fact in buckets.current_facts
        if any(item.startswith("superseded_by:") for item in fact.relation_summary)
    )


def _evidence_refs(metadata: ContextMetadataPayload) -> tuple[str, ...]:
    """Execute evidence refs.

    Args:
        metadata: Metadata used by this operation.

    Returns:
        tuple[str, ...] result produced by evidence refs.
    """
    value: JSONValue | None = metadata.get("evidence_refs")
    if not isinstance(value, list):
        return ()
    return tuple(
        dict.fromkeys(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )
    )


def _datetime_text(value: datetime | None) -> str:
    """Execute datetime text.

    Args:
        value: Value being processed.

    Returns:
        str result produced by datetime text.
    """
    if value is None:
        return "open"
    return value.isoformat()
