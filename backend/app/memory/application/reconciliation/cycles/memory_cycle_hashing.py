"""Canonical source-set and semantic plan hashing for Memory cycles."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

from typing_extensions import TypedDict

from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.entities.memory_cycle import (
    MemoryCycleCompactChange,
    MemoryCycleCompactSnapshot,
    MemoryCycleSourceSnapshot,
)
from app.memory.domain.entities.memory_reconciliation import MemoryReconciliationPlan
from app.memory.domain.event_enum.memory_cycle_enums import MemoryCycleOperation
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.types_convert_utils import aware_utc_datetime


class SourceRefHashDict(TypedDict, closed=True):
    """Canonical hash entry for one Memory Compact source reference."""

    source_type: str
    source_id: str
    detail_path: str
    source_hash: str | None


class SemanticPlanDecisionHashDict(TypedDict, closed=True):
    """Canonical hash entry for one child reconciliation decision."""

    existing_context_id: str
    relation: str
    confidence: float
    reason: str
    claim_matches: list[str]
    policy_version: str


class SemanticPlanActionHashDict(TypedDict, closed=True):
    """Canonical hash entry for one child reconciliation action."""

    action_type: str
    target_context_id: str | None
    relation: str | None
    reason: str


class SemanticPlanChildHashDict(TypedDict, closed=True):
    """Canonical hash entry for one child reconciliation plan."""

    idempotency_key: str
    candidate_id: str
    candidate_content_hash: str
    primary_decision: str
    requires_review: bool
    warnings: list[str]
    decisions: list[SemanticPlanDecisionHashDict]
    actions: list[SemanticPlanActionHashDict]


class SemanticPlanSourceSnapshotHashDict(TypedDict, closed=True):
    """Canonical hash entry for one admitted cycle source snapshot."""

    context_id: str
    canonical_path: str
    content_hash: str
    source_revision: str


class SemanticPlanCurrentCompactHashDict(TypedDict, closed=True):
    """Canonical hash entry for the existing CURRENT Compact snapshot."""

    compact_id: str
    content_hash: str
    source_set_hash: str | None
    status: str


class SemanticPlanCompactChangeHashDict(TypedDict, closed=True):
    """Canonical hash entry for the planned Compact mutation metadata."""

    status: str | None
    content_hash: str | None
    source_set_hash: str | None
    safe_to_publish: bool
    warnings: list[str]


class SemanticPlanHashDict(TypedDict, closed=True):
    """Canonical hash payload for the entire semantic memory cycle plan."""

    operation: str
    project: str | None
    workspace_id: str | None
    scope: str | None
    window_start: str
    window_end: str
    max_contexts: int
    source_snapshot: list[SemanticPlanSourceSnapshotHashDict]
    current_compact: SemanticPlanCurrentCompactHashDict | None
    children: list[SemanticPlanChildHashDict]
    compact: SemanticPlanCompactChangeHashDict


def source_set_hash(source_refs: tuple[MemoryCompactSourceRefCreate, ...]) -> str:
    """Hash the exact sorted source set used by a Compact candidate.

    Args:
        source_refs: Sorted source references attached to the Compact candidate.

    Returns:
        SHA-256 hex digest of the canonical JSON source-reference list.
    """
    payload: list[SourceRefHashDict] = [
        SourceRefHashDict(
            source_type=item.source_type,
            source_id=item.source_id,
            detail_path=item.detail_path,
            source_hash=item.source_hash,
        )
        for item in source_refs
    ]
    return sha256(dumps_canonical_json(payload)).hexdigest()


def compact_source_hashes_match(
    compact: MemoryCompact,
    source_snapshot: tuple[MemoryCycleSourceSnapshot, ...],
) -> bool:
    """Verify each selected Compact ref against the admitted source set.

    A Compact may intentionally summarize a subset of the consulted cycle
    sources. Every persisted ref must still bind to one exact source identity
    and post-apply hash, and an identity may occur only once.

    Args:
        compact: Persisted Memory Compact to verify.
        source_snapshot: Admitted source snapshots for the cycle.

    Returns:
        True when every Compact source ref matches a unique snapshot hash.
    """
    expected = {item.context_id: item.content_hash for item in source_snapshot}
    seen: set[str] = set()
    for source_ref in compact.source_refs:
        if source_ref.source_id in seen:
            return False
        seen.add(source_ref.source_id)
        if source_ref.source_id not in expected:
            return False
        if source_ref.source_hash != expected[source_ref.source_id]:
            return False
    return True


def compact_payload_for_sources(
    payload: MemoryCompactCreate,
    source_snapshot: tuple[MemoryCycleSourceSnapshot, ...],
) -> MemoryCompactCreate:
    """Refresh Compact source hashes after intentional child mutations.

    Args:
        payload: Draft Compact creation payload from preview planning.
        source_snapshot: Updated source snapshots after child reconciliation.

    Returns:
        Compact creation payload with refreshed source hashes.
    """
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
    """Hash semantic cycle inputs while excluding random IDs and timestamps.

    Args:
        request: Validated memory-cycle request parameters.
        source_snapshot: Admitted source snapshots for the cycle window.
        current_compact: Snapshot of the existing CURRENT Compact, if any.
        plans: Child reconciliation plans included in the cycle.
        compact_change: Planned Compact mutation metadata.

    Returns:
        Deterministic SHA-256 hex digest of the canonical semantic plan.
    """
    children: list[SemanticPlanChildHashDict] = [
        SemanticPlanChildHashDict(
            idempotency_key=plan.idempotency_key,
            candidate_id=plan.candidate.candidate_id,
            candidate_content_hash=plan.candidate.content_hash,
            primary_decision=plan.primary_decision.value,
            requires_review=plan.requires_review,
            warnings=list(plan.warnings),
            decisions=[
                SemanticPlanDecisionHashDict(
                    existing_context_id=decision.existing_context_id,
                    relation=decision.relation.value,
                    confidence=decision.confidence,
                    reason=decision.reason,
                    claim_matches=list(decision.claim_matches),
                    policy_version=decision.policy_version,
                )
                for decision in sorted(
                    plan.decisions,
                    key=lambda item: (
                        item.existing_context_id,
                        item.relation.value,
                        item.reason,
                    ),
                )
            ],
            actions=[
                SemanticPlanActionHashDict(
                    action_type=action.action_type.value,
                    target_context_id=action.target_context_id,
                    relation=(
                        None if action.relation is None else action.relation.value
                    ),
                    reason=action.reason,
                )
                for action in plan.actions
            ],
        )
        for plan in sorted(plans, key=lambda item: item.idempotency_key)
    ]
    payload = SemanticPlanHashDict(
        operation=MemoryCycleOperation.DRY_RUN.value,
        project=request.project,
        workspace_id=request.workspace_id,
        scope=None if request.scope is None else request.scope.value,
        window_start=aware_utc_datetime(request.window_start).isoformat(),
        window_end=aware_utc_datetime(request.window_end).isoformat(),
        max_contexts=request.max_contexts,
        source_snapshot=[
            SemanticPlanSourceSnapshotHashDict(
                context_id=item.context_id,
                canonical_path=item.canonical_path,
                content_hash=item.content_hash,
                source_revision=item.source_revision,
            )
            for item in source_snapshot
        ],
        current_compact=(
            None
            if current_compact is None
            else SemanticPlanCurrentCompactHashDict(
                compact_id=current_compact.compact_id,
                content_hash=current_compact.content_hash,
                source_set_hash=current_compact.source_set_hash,
                status=current_compact.status.value,
            )
        ),
        children=children,
        compact=SemanticPlanCompactChangeHashDict(
            status=(
                None if compact_change.status is None else compact_change.status.value
            ),
            content_hash=compact_change.content_hash,
            source_set_hash=compact_change.source_set_hash,
            safe_to_publish=compact_change.safe_to_publish,
            warnings=list(compact_change.warnings),
        ),
    )
    return sha256(dumps_canonical_json(payload)).hexdigest()
