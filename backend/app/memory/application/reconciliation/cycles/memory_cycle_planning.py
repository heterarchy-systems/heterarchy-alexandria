"""Pure planning and Compact rendering for Memory cycles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_policy import (
    render_fact_buckets,
)
from app.memory.application.reconciliation.cycles.memory_cycle_hashing import (
    source_set_hash,
)
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.entities.memory_cycle import (
    MemoryCycleBuckets,
    MemoryCycleCandidate,
    MemoryCycleCompactSnapshot,
)
from app.memory.domain.entities.memory_existing_reconciliation import (
    ExistingMemoryPlanPreview,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCompactFact,
    MemoryCompactFactBuckets,
    MemoryCompactSafetyReview,
    MemoryReconciliationPlan,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryCompactFactCategory,
    MemoryRelationType,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactSourceRefCreate,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.types.extra_types import JSONValue


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCyclePlanningFacts:
    """Typed policy input assembled from existing reconciliation previews."""

    buckets: MemoryCycleBuckets
    fact_buckets: MemoryCompactFactBuckets
    source_refs: tuple[MemoryCompactSourceRefCreate, ...]
    source_set_hash: str


@dataclass(slots=True)
class _MemoryCycleFactAccumulator:
    """Stateful accumulator for candidate buckets and Compact facts across cycle previews."""

    retained: list[MemoryCycleCandidate] = field(default_factory=list)
    duplicates: list[MemoryCycleCandidate] = field(default_factory=list)
    supersession: list[MemoryCycleCandidate] = field(default_factory=list)
    contradictions: list[MemoryCycleCandidate] = field(default_factory=list)
    summary: list[MemoryCycleCandidate] = field(default_factory=list)
    relations: list[MemoryCycleCandidate] = field(default_factory=list)
    review: list[MemoryCycleCandidate] = field(default_factory=list)
    facts_by_category: dict[MemoryCompactFactCategory, list[MemoryCompactFact]] = field(
        default_factory=lambda: {category: [] for category in MemoryCompactFactCategory}
    )
    source_refs: list[MemoryCompactSourceRefCreate] = field(default_factory=list)

    def record_preview(self, item: ExistingMemoryPlanPreview) -> None:
        """Classify and record one child reconciliation preview item.

        Args:
            item: Child reconciliation preview item.
        """
        plan = item.plan
        relation = None if plan is None else plan.primary_decision
        targets = (
            ()
            if plan is None
            else tuple(
                sorted({decision.existing_context_id for decision in plan.decisions})
            )
        )
        candidate = MemoryCycleCandidate(
            context_id=item.context.id,
            title=item.context.title,
            canonical_path=item.canonical_path,
            content_hash=item.content_hash,
            relation=relation,
            target_context_ids=targets,
            child_plan_key=None if plan is None else plan.idempotency_key,
            reason=(
                "No safe child relation was proposed"
                if plan is None
                else self._plan_reason(plan)
            ),
            requires_review=False if plan is None else plan.requires_review,
        )
        self.source_refs.append(
            MemoryCompactSourceRefCreate(
                source_type=item.context.source_type.value,
                source_id=item.context.id,
                title=item.context.title,
                detail_path=item.canonical_path,
                source_hash=item.content_hash,
            )
        )
        fact_category = self._fact_category_for(item, relation)
        if relation is MemoryRelationType.DUPLICATE:
            self.duplicates.append(candidate)
        elif relation is MemoryRelationType.CONTRADICTS:
            self.contradictions.append(candidate)
            self.review.append(candidate)
        elif relation is MemoryRelationType.SUPERSEDES:
            self.supersession.append(candidate)
            self.review.append(candidate)
        elif plan is not None and plan.requires_review:
            self.review.append(candidate)
        else:
            self.retained.append(candidate)
        if plan is not None and relation in {
            MemoryRelationType.SUPPORTS,
            MemoryRelationType.EXTENDS,
        }:
            self.relations.append(candidate)
        if plan is None or relation in {
            MemoryRelationType.SUPPORTS,
            MemoryRelationType.EXTENDS,
        }:
            self.summary.append(candidate)
        if relation is not MemoryRelationType.DUPLICATE:
            self.facts_by_category[fact_category].append(
                self._memory_compact_fact(item, relation, fact_category)
            )

    def finalize(self) -> MemoryCyclePlanningFacts:
        """Freeze accumulated buckets, facts, and sorted source references.

        Returns:
            Assembled cycle buckets, Compact fact buckets, and source-set hash.
        """
        facts = MemoryCompactFactBuckets(
            current_facts=tuple(
                self.facts_by_category[MemoryCompactFactCategory.CURRENT]
            ),
            historical_facts=tuple(
                self.facts_by_category[MemoryCompactFactCategory.HISTORICAL]
            ),
            open_conflicts=tuple(
                self.facts_by_category[MemoryCompactFactCategory.OPEN_CONFLICT]
            ),
            uncertain_claims=tuple(
                self.facts_by_category[MemoryCompactFactCategory.UNCERTAIN]
            ),
            superseded_facts=tuple(
                self.facts_by_category[MemoryCompactFactCategory.SUPERSEDED]
            ),
        )
        buckets = MemoryCycleBuckets(
            retained_facts=tuple(self.retained),
            duplicates=tuple(self.duplicates),
            supersession_candidates=tuple(self.supersession),
            contradictions=tuple(self.contradictions),
            summary_candidates=tuple(self.summary),
            relationship_changes=tuple(self.relations),
            archive_candidates=(),
            review_required=tuple(self.review),
        )
        source_refs_tuple = tuple(
            sorted(
                self.source_refs,
                key=lambda item: (item.source_type, item.source_id, item.detail_path),
            )
        )
        return MemoryCyclePlanningFacts(
            buckets=buckets,
            fact_buckets=facts,
            source_refs=source_refs_tuple,
            source_set_hash=source_set_hash(source_refs_tuple),
        )

    @staticmethod
    def _fact_category_for(
        item: ExistingMemoryPlanPreview,
        relation: MemoryRelationType | None,
    ) -> MemoryCompactFactCategory:
        """Select a Compact category without collapsing temporal state.

        Args:
            item: Child reconciliation preview item.
            relation: Primary proposed relation for the item, if any.

        Returns:
            Selected Compact fact category.
        """
        if relation is MemoryRelationType.CONTRADICTS:
            return MemoryCompactFactCategory.OPEN_CONFLICT
        if relation is MemoryRelationType.SUPERSEDES:
            return MemoryCompactFactCategory.SUPERSEDED
        if item.temporal.conflict_set_ids:
            return MemoryCompactFactCategory.OPEN_CONFLICT
        if item.temporal.superseded_by:
            return MemoryCompactFactCategory.SUPERSEDED
        if item.temporal.is_current:
            return MemoryCompactFactCategory.CURRENT
        if item.temporal.valid_to is not None:
            return MemoryCompactFactCategory.HISTORICAL
        return MemoryCompactFactCategory.UNCERTAIN

    @classmethod
    def _memory_compact_fact(
        cls,
        item: ExistingMemoryPlanPreview,
        relation: MemoryRelationType | None,
        category: MemoryCompactFactCategory,
    ) -> MemoryCompactFact:
        """Map one selected Context into an existing Compact fact bucket.

        Args:
            item: Child reconciliation preview item.
            relation: Primary proposed relation for the item, if any.
            category: Assigned Compact fact category.

        Returns:
            Constructed Compact fact entry.
        """
        relation_label = None if relation is None else relation.value.lower()
        target_ids = (
            ()
            if item.plan is None
            else sorted(
                {decision.existing_context_id for decision in item.plan.decisions}
            )
        )
        relation_summary = (
            *item.temporal.relation_summary,
            *(
                ()
                if relation_label is None
                else tuple(f"{relation_label}:{target}" for target in target_ids)
            ),
        )
        return MemoryCompactFact(
            context_id=item.context.id,
            title=item.context.title,
            content=item.context.content,
            category=category,
            valid_from=item.temporal.valid_from,
            valid_to=item.temporal.valid_to,
            evidence_refs=(cls._canonical_path(item.context),),
            conflict_set_ids=item.temporal.conflict_set_ids,
            relation_summary=relation_summary,
        )

    @staticmethod
    def _plan_reason(plan: MemoryReconciliationPlan) -> str:
        """Return the selected primary relation explanation.

        Args:
            plan: Child reconciliation plan.

        Returns:
            Primary relation explanation string.
        """
        for decision in plan.decisions:
            if decision.existing_context_id in plan.conflicting_context_ids:
                return decision.reason
        return plan.warnings[0] if plan.warnings else plan.primary_decision.value

    @staticmethod
    def _canonical_path(context: ContextRecord) -> str:
        """Return the source path from existing Context metadata.

        Args:
            context: Context record to inspect.

        Returns:
            Normalized relative path or fallback context identifier.
        """
        value: JSONValue | None = context.context_metadata.get("relative_path")
        return (
            value.strip()
            if isinstance(value, str) and value.strip()
            else f"context:{context.id}"
        )


def compact_snapshot(
    compact: MemoryCompact | None,
) -> MemoryCycleCompactSnapshot | None:
    """Map one trusted Compact into a stable planning snapshot.

    Args:
        compact: Trusted CURRENT Memory Compact, if one exists.

    Returns:
        Stable Compact snapshot or None.
    """
    if compact is None:
        return None
    return MemoryCycleCompactSnapshot(
        compact_id=compact.id,
        content_hash=hash_text(compact.markdown_body),
        source_set_hash=compact.source_set_hash,
        status=compact.status,
    )


def build_cycle_facts(
    previews: tuple[ExistingMemoryPlanPreview, ...],
) -> MemoryCyclePlanningFacts:
    """Map child plans into explicit cycle buckets and Compact facts.

    Args:
        previews: Child reconciliation plan previews for the cycle window.

    Returns:
        Assembled cycle buckets, Compact fact buckets, and source-set hash.
    """
    accumulator = _MemoryCycleFactAccumulator()
    for item in previews:
        accumulator.record_preview(item)
    return accumulator.finalize()


def compact_blockers(
    buckets: MemoryCycleBuckets,
    review: MemoryCompactSafetyReview,
) -> tuple[str, ...]:
    """Return aggregate Compact blockers while preserving policy review.

    Args:
        buckets: Assembled candidate buckets for the cycle.
        review: Safety review verdict for the rendered Compact body.

    Returns:
        Deduplicated tuple of blocker warning strings.
    """
    warnings = list(review.warnings)
    if buckets.contradictions:
        warnings.append("unresolved contradiction candidates require review")
    if buckets.supersession_candidates:
        warnings.append("supersession candidates require explicit review")
    if buckets.review_required:
        warnings.append("one or more child reconciliation plans require review")
    if not review.safe_to_publish:
        warnings.append("Memory Compact policy review did not pass")
    return tuple(dict.fromkeys(warnings))


def render_compact_body(
    project: str | None,
    window_start: datetime,
    window_end: datetime,
    facts: MemoryCompactFactBuckets,
    blockers: tuple[str, ...],
) -> str:
    """Render required Compact sections with source-cited fact content.

    Args:
        project: Project identifier or None for default.
        window_start: Covered window start timestamp.
        window_end: Covered window end timestamp.
        facts: Categorized Compact fact buckets.
        blockers: Aggregate reconciliation blocker strings.

    Returns:
        Rendered Markdown body for the Memory Compact.
    """
    rendered_facts = render_fact_buckets(facts)
    risk_lines = [f"- {item}" for item in blockers] or [
        "- No unresolved reconciliation blockers were found."
    ]
    action_lines = (
        ["- Review the listed candidates before promotion."]
        if blockers
        else ["- Continue bounded retrieval verification for this project window."]
    )
    project_text = project or "default"
    evidence_lines = [
        f"- {fact.context_id} — source: `{fact.evidence_refs[0]}`."
        for fact in (
            *facts.current_facts,
            *facts.historical_facts,
            *facts.open_conflicts,
            *facts.uncertain_claims,
            *facts.superseded_facts,
        )
        if fact.evidence_refs
    ] or ["- No selected source facts."]
    return "\n".join(
        [
            "# Alexandria Memory Compact",
            "",
            "## Durable Decisions",
            f"- Project `{project_text}` memory cycle facts remain source cited.",
            "",
            "## Current State",
            f"- Project: `{project_text}`.",
            f"- Window: `{window_start.isoformat()}` → `{window_end.isoformat()}`.",
            rendered_facts,
            "",
            "## Risks and Blockers",
            *risk_lines,
            "",
            "## Next Actions",
            *action_lines,
            "",
            "## Coverage",
            f"- covered_from: `{window_start.isoformat()}`.",
            f"- covered_to: `{window_end.isoformat()}`.",
            f"- project: `{project_text}`.",
            "",
            "## Evidence Summary",
            *evidence_lines,
            "",
        ]
    )
