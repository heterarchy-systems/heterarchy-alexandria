"""Strict aggregate response schemas for memory-cycle operations."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.memory.domain.entities.memory_cycle import (
    MemoryCycleBuckets,
    MemoryCycleChildOutcome,
    MemoryCyclePhase,
    MemoryCycleResult,
)
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleOperation,
    MemoryCyclePhaseStatus,
    MemoryCycleStatus,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryRelationType
from app.memory.interface.schemas.reconciliation.cycles.memory_cycle_snapshot_schema import (
    MemoryCycleCandidateResponse,
    MemoryCycleCompactChangeResponse,
    MemoryCycleCompactSnapshotResponse,
    MemoryCycleSourceSnapshotResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel


class MemoryCycleBucketsResponse(StrictSchemaModel):
    """All bounded candidate buckets returned by the cycle."""

    retained_facts: Annotated[
        list[MemoryCycleCandidateResponse], Field(description="Retained facts.")
    ]
    duplicates: Annotated[
        list[MemoryCycleCandidateResponse], Field(description="Duplicate candidates.")
    ]
    supersession_candidates: Annotated[
        list[MemoryCycleCandidateResponse],
        Field(description="Supersession candidates."),
    ]
    contradictions: Annotated[
        list[MemoryCycleCandidateResponse],
        Field(description="Contradiction candidates."),
    ]
    compact_changes: Annotated[
        list[MemoryCycleCompactChangeResponse], Field(description="Compact changes.")
    ]
    summary_candidates: Annotated[
        list[MemoryCycleCandidateResponse], Field(description="Summary candidates.")
    ]
    relationship_changes: Annotated[
        list[MemoryCycleCandidateResponse],
        Field(description="Safe relationship changes."),
    ]
    archive_candidates: Annotated[
        list[MemoryCycleCandidateResponse], Field(description="Archive candidates.")
    ]
    review_required: Annotated[
        list[MemoryCycleCandidateResponse],
        Field(description="Review-required candidates."),
    ]

    @classmethod
    def from_entity(cls, value: MemoryCycleBuckets) -> MemoryCycleBucketsResponse:
        """Map all cycle buckets."""
        candidate = MemoryCycleCandidateResponse.from_entity
        return cls(
            retained_facts=[candidate(item) for item in value.retained_facts],
            duplicates=[candidate(item) for item in value.duplicates],
            supersession_candidates=[
                candidate(item) for item in value.supersession_candidates
            ],
            contradictions=[candidate(item) for item in value.contradictions],
            compact_changes=[
                MemoryCycleCompactChangeResponse.from_entity(item)
                for item in value.compact_changes
            ],
            summary_candidates=[candidate(item) for item in value.summary_candidates],
            relationship_changes=[
                candidate(item) for item in value.relationship_changes
            ],
            archive_candidates=[candidate(item) for item in value.archive_candidates],
            review_required=[candidate(item) for item in value.review_required],
        )


class MemoryCycleChildOutcomeResponse(StrictSchemaModel):
    """Child plan/result evidence."""

    child_plan_key: Annotated[str, Field(description="Stable child plan key.")]
    plan_id: Annotated[str | None, Field(description="Persisted child plan identity.")]
    result_id: Annotated[
        str | None, Field(description="Persisted child result identity.")
    ]
    relation: Annotated[MemoryRelationType, Field(description="Child relation.")]
    status: Annotated[str, Field(description="Child lifecycle status.")]
    requires_review: Annotated[
        bool, Field(description="Whether child review is required.")
    ]
    warnings: Annotated[list[str], Field(description="Child warnings.")]
    affected_context_ids: Annotated[
        list[str],
        Field(description="Canonical Context identities affected by the child."),
    ]

    @classmethod
    def from_entity(
        cls, value: MemoryCycleChildOutcome
    ) -> MemoryCycleChildOutcomeResponse:
        """Map one child outcome."""
        return cls(
            child_plan_key=value.child_plan_key,
            plan_id=value.plan_id,
            result_id=value.result_id,
            relation=value.relation,
            status=value.status,
            requires_review=value.requires_review,
            warnings=list(value.warnings),
            affected_context_ids=list(value.affected_context_ids),
        )


class MemoryCyclePhaseResponse(StrictSchemaModel):
    """Phase-level aggregate evidence."""

    name: Annotated[str, Field(description="Phase name.")]
    status: Annotated[MemoryCyclePhaseStatus, Field(description="Phase status.")]
    detail: Annotated[str, Field(description="Bounded phase detail.")]
    warnings: Annotated[list[str], Field(description="Phase warnings.")]

    @classmethod
    def from_entity(cls, value: MemoryCyclePhase) -> MemoryCyclePhaseResponse:
        """Map one phase."""
        return cls(
            name=value.name,
            status=value.status,
            detail=value.detail,
            warnings=list(value.warnings),
        )


class MemoryCycleResponseSchema(StrictSchemaModel):
    """Typed agent-facing memory-cycle response."""

    operation: Annotated[MemoryCycleOperation, Field(description="Cycle operation.")]
    status: Annotated[MemoryCycleStatus, Field(description="Aggregate cycle status.")]
    idempotency_key: Annotated[str, Field(description="Cycle idempotency key.")]
    plan_hash: Annotated[str, Field(description="Deterministic semantic plan hash.")]
    project: Annotated[str, Field(description="Project identity.")]
    workspace_id: Annotated[str | None, Field(description="Workspace identity.")]
    scope: Annotated[str | None, Field(description="Strict Context scope.")]
    window_start: Annotated[datetime, Field(description="Window start.")]
    window_end: Annotated[datetime, Field(description="Window end.")]
    replayed: Annotated[
        bool, Field(description="Whether a verified checkpoint was replayed.")
    ]
    scanned: Annotated[int, Field(description="Contexts scanned.")]
    total_available: Annotated[int, Field(description="Total matching Contexts.")]
    candidate_count: Annotated[int, Field(description="Bounded candidate count.")]
    source_snapshot: Annotated[
        list[MemoryCycleSourceSnapshotResponse], Field(description="Source provenance.")
    ]
    current_compact: Annotated[
        MemoryCycleCompactSnapshotResponse | None,
        Field(description="Current Compact planning snapshot."),
    ]
    buckets: Annotated[
        MemoryCycleBucketsResponse, Field(description="Typed cycle buckets.")
    ]
    child_outcomes: Annotated[
        list[MemoryCycleChildOutcomeResponse], Field(description="Child plan outcomes.")
    ]
    compact_change: Annotated[
        MemoryCycleCompactChangeResponse | None,
        Field(description="Compact publication outcome."),
    ]
    phases: Annotated[
        list[MemoryCyclePhaseResponse], Field(description="Phase evidence.")
    ]
    warnings: Annotated[list[str], Field(description="Aggregate warnings.")]
    elapsed_ms: Annotated[
        float, Field(description="Observed cycle latency in milliseconds.")
    ]
    query_count: Annotated[
        int | None, Field(description="Measured query count when instrumented.")
    ]
    hard_delete_performed: Annotated[
        bool, Field(description="Whether any hard delete occurred.")
    ]

    @classmethod
    def from_entity(cls, value: MemoryCycleResult) -> MemoryCycleResponseSchema:
        """Map one aggregate cycle result."""
        return cls(
            operation=value.operation,
            status=value.status,
            idempotency_key=value.idempotency_key,
            plan_hash=value.plan_hash,
            project=value.project,
            workspace_id=value.workspace_id,
            scope=value.scope,
            window_start=value.window_start,
            window_end=value.window_end,
            replayed=value.replayed,
            scanned=value.scanned,
            total_available=value.total_available,
            candidate_count=value.candidate_count,
            source_snapshot=[
                MemoryCycleSourceSnapshotResponse.from_entity(item)
                for item in value.source_snapshot
            ],
            current_compact=(
                None
                if value.current_compact is None
                else MemoryCycleCompactSnapshotResponse.from_entity(
                    value.current_compact
                )
            ),
            buckets=MemoryCycleBucketsResponse.from_entity(value.buckets),
            child_outcomes=[
                MemoryCycleChildOutcomeResponse.from_entity(item)
                for item in value.child_outcomes
            ],
            compact_change=(
                None
                if value.compact_change is None
                else MemoryCycleCompactChangeResponse.from_entity(value.compact_change)
            ),
            phases=[
                MemoryCyclePhaseResponse.from_entity(item) for item in value.phases
            ],
            warnings=list(value.warnings),
            elapsed_ms=value.elapsed_ms,
            query_count=value.query_count,
            hard_delete_performed=value.hard_delete_performed,
        )
