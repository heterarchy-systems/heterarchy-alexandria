"""Pure planning, hashing, and Compact rendering for Memory cycles."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256

from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_policy import (
    render_fact_buckets,
)
from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.entities.memory_cycle import (
    MemoryCycleBuckets,
    MemoryCycleCandidate,
    MemoryCycleCompactChange,
    MemoryCycleCompactSnapshot,
    MemoryCycleSourceSnapshot,
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
from app.memory.domain.event_enum.memory_cycle_enums import MemoryCycleOperation
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryCompactFactCategory,
    MemoryRelationType,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject, JSONValue
from app.shared.types.types_convert_utils import aware_utc_datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCyclePlanningFacts:
    """Typed policy input assembled from existing reconciliation previews."""

    buckets: MemoryCycleBuckets
    fact_buckets: MemoryCompactFactBuckets
    source_refs: tuple[MemoryCompactSourceRefCreate, ...]
    source_set_hash: str


def compact_snapshot(
    compact: MemoryCompact | None,
) -> MemoryCycleCompactSnapshot | None:
    """Map one trusted Compact into a stable planning snapshot."""
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
    """Map child plans into explicit cycle buckets and Compact facts."""
    retained: list[MemoryCycleCandidate] = []
    duplicates: list[MemoryCycleCandidate] = []
    supersession: list[MemoryCycleCandidate] = []
    contradictions: list[MemoryCycleCandidate] = []
    summary: list[MemoryCycleCandidate] = []
    relations: list[MemoryCycleCandidate] = []
    review: list[MemoryCycleCandidate] = []
    facts_by_category: dict[MemoryCompactFactCategory, list[MemoryCompactFact]] = {
        category: [] for category in MemoryCompactFactCategory
    }
    source_refs: list[MemoryCompactSourceRefCreate] = []
    for item in previews:
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
                else plan_reason(plan)
            ),
            requires_review=False if plan is None else plan.requires_review,
        )
        source_refs.append(
            MemoryCompactSourceRefCreate(
                source_type=item.context.source_type.value,
                source_id=item.context.id,
                title=item.context.title,
                detail_path=item.canonical_path,
                source_hash=item.content_hash,
            )
        )
        fact_category = fact_category_for(item, relation)
        if relation is MemoryRelationType.DUPLICATE:
            duplicates.append(candidate)
        elif relation is MemoryRelationType.CONTRADICTS:
            contradictions.append(candidate)
            review.append(candidate)
        elif relation is MemoryRelationType.SUPERSEDES:
            supersession.append(candidate)
            review.append(candidate)
        elif plan is not None and plan.requires_review:
            review.append(candidate)
        else:
            retained.append(candidate)
        if plan is not None and relation in {
            MemoryRelationType.SUPPORTS,
            MemoryRelationType.EXTENDS,
        }:
            relations.append(candidate)
        if plan is None or relation in {
            MemoryRelationType.SUPPORTS,
            MemoryRelationType.EXTENDS,
        }:
            summary.append(candidate)
        if relation is not MemoryRelationType.DUPLICATE:
            facts_by_category[fact_category].append(
                memory_compact_fact(item, relation, fact_category)
            )
    facts = MemoryCompactFactBuckets(
        current_facts=tuple(facts_by_category[MemoryCompactFactCategory.CURRENT]),
        historical_facts=tuple(facts_by_category[MemoryCompactFactCategory.HISTORICAL]),
        open_conflicts=tuple(
            facts_by_category[MemoryCompactFactCategory.OPEN_CONFLICT]
        ),
        uncertain_claims=tuple(facts_by_category[MemoryCompactFactCategory.UNCERTAIN]),
        superseded_facts=tuple(facts_by_category[MemoryCompactFactCategory.SUPERSEDED]),
    )
    buckets = MemoryCycleBuckets(
        retained_facts=tuple(retained),
        duplicates=tuple(duplicates),
        supersession_candidates=tuple(supersession),
        contradictions=tuple(contradictions),
        summary_candidates=tuple(summary),
        relationship_changes=tuple(relations),
        archive_candidates=(),
        review_required=tuple(review),
    )
    source_refs_tuple = tuple(
        sorted(
            source_refs,
            key=lambda item: (item.source_type, item.source_id, item.detail_path),
        )
    )
    return MemoryCyclePlanningFacts(
        buckets=buckets,
        fact_buckets=facts,
        source_refs=source_refs_tuple,
        source_set_hash=source_set_hash(source_refs_tuple),
    )


def fact_category_for(
    item: ExistingMemoryPlanPreview,
    relation: MemoryRelationType | None,
) -> MemoryCompactFactCategory:
    """Select a Compact category without collapsing temporal state."""
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


def memory_compact_fact(
    item: ExistingMemoryPlanPreview,
    relation: MemoryRelationType | None,
    category: MemoryCompactFactCategory,
) -> MemoryCompactFact:
    """Map one selected Context into an existing Compact fact bucket."""
    relation_label = None if relation is None else relation.value.lower()
    target_ids = (
        ()
        if item.plan is None
        else sorted({decision.existing_context_id for decision in item.plan.decisions})
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
        evidence_refs=(canonical_path(item.context),),
        conflict_set_ids=item.temporal.conflict_set_ids,
        relation_summary=relation_summary,
    )


def plan_reason(plan: MemoryReconciliationPlan) -> str:
    """Return the selected primary relation explanation."""
    for decision in plan.decisions:
        if decision.existing_context_id in plan.conflicting_context_ids:
            return decision.reason
    return plan.warnings[0] if plan.warnings else plan.primary_decision.value


def compact_blockers(
    buckets: MemoryCycleBuckets,
    review: MemoryCompactSafetyReview,
) -> tuple[str, ...]:
    """Return aggregate Compact blockers while preserving policy review."""
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
    """Render required Compact sections with source-cited fact content."""
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


def source_set_hash(source_refs: tuple[MemoryCompactSourceRefCreate, ...]) -> str:
    """Hash the exact sorted source set used by a Compact candidate."""
    payload: list[JSONObject] = [
        {
            "source_type": item.source_type,
            "source_id": item.source_id,
            "detail_path": item.detail_path,
            "source_hash": item.source_hash,
        }
        for item in source_refs
    ]
    return sha256(dumps_canonical_json(payload)).hexdigest()


def compact_source_hashes_match(
    compact: MemoryCompact,
    source_snapshot: tuple[MemoryCycleSourceSnapshot, ...],
) -> bool:
    """Verify every Compact source ref against the admitted source set."""
    expected = {item.context_id: item.content_hash for item in source_snapshot}
    if len(compact.source_refs) != len(expected):
        return False
    return all(
        source_ref.source_hash == expected.get(source_ref.source_id)
        for source_ref in compact.source_refs
    )


def compact_payload_for_sources(
    payload: MemoryCompactCreate,
    source_snapshot: tuple[MemoryCycleSourceSnapshot, ...],
) -> MemoryCompactCreate:
    """Refresh Compact source hashes after intentional child mutations."""
    hashes = {item.context_id: item.content_hash for item in source_snapshot}
    source_refs = tuple(
        replace(
            source_ref,
            source_hash=hashes.get(source_ref.source_id, source_ref.source_hash),
        )
        for source_ref in payload.source_refs
    )
    return replace(payload, source_refs=source_refs)


def semantic_plan_hash(
    request: MemoryCycleRequest,
    source_snapshot: tuple[MemoryCycleSourceSnapshot, ...],
    current_compact: MemoryCycleCompactSnapshot | None,
    plans: tuple[MemoryReconciliationPlan, ...],
    compact_change: MemoryCycleCompactChange,
) -> str:
    """Hash semantic cycle inputs while excluding random IDs and timestamps."""
    children: list[JSONObject] = [
        {
            "idempotency_key": plan.idempotency_key,
            "candidate_id": plan.candidate.candidate_id,
            "candidate_content_hash": plan.candidate.content_hash,
            "primary_decision": plan.primary_decision.value,
            "requires_review": plan.requires_review,
            "warnings": list(plan.warnings),
            "decisions": [
                {
                    "existing_context_id": decision.existing_context_id,
                    "relation": decision.relation.value,
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                    "claim_matches": list(decision.claim_matches),
                    "policy_version": decision.policy_version,
                }
                for decision in sorted(
                    plan.decisions,
                    key=lambda item: (
                        item.existing_context_id,
                        item.relation.value,
                        item.reason,
                    ),
                )
            ],
            "actions": [
                {
                    "action_type": action.action_type.value,
                    "target_context_id": action.target_context_id,
                    "relation": None
                    if action.relation is None
                    else action.relation.value,
                    "reason": action.reason,
                }
                for action in plan.actions
            ],
        }
        for plan in sorted(plans, key=lambda item: item.idempotency_key)
    ]
    payload: JSONObject = {
        "operation": MemoryCycleOperation.DRY_RUN.value,
        "project": request.project,
        "workspace_id": request.workspace_id,
        "scope": None if request.scope is None else request.scope.value,
        "window_start": aware_utc_datetime(request.window_start).isoformat(),
        "window_end": aware_utc_datetime(request.window_end).isoformat(),
        "max_contexts": request.max_contexts,
        "source_snapshot": [
            {
                "context_id": item.context_id,
                "canonical_path": item.canonical_path,
                "content_hash": item.content_hash,
                "source_revision": item.source_revision,
            }
            for item in source_snapshot
        ],
        "current_compact": (
            None
            if current_compact is None
            else {
                "compact_id": current_compact.compact_id,
                "content_hash": current_compact.content_hash,
                "source_set_hash": current_compact.source_set_hash,
                "status": current_compact.status.value,
            }
        ),
        "children": children,
        "compact": {
            "status": None
            if compact_change.status is None
            else compact_change.status.value,
            "content_hash": compact_change.content_hash,
            "source_set_hash": compact_change.source_set_hash,
            "safe_to_publish": compact_change.safe_to_publish,
            "warnings": list(compact_change.warnings),
        },
    }
    return sha256(dumps_canonical_json(payload)).hexdigest()


def canonical_path(context: ContextRecord) -> str:
    """Return the source path from existing Context metadata."""
    value: JSONValue | None = context.context_metadata.get("relative_path")
    return (
        value.strip()
        if isinstance(value, str) and value.strip()
        else f"context:{context.id}"
    )
