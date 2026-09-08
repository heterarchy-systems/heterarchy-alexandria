"""Strict HTTP/MCP schemas for the high-level memory-cycle contract."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, ValidationInfo, field_validator

from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.entities.memory_cycle import (
    MemoryCycleBuckets,
    MemoryCycleCandidate,
    MemoryCycleChildOutcome,
    MemoryCycleCompactChange,
    MemoryCycleCompactSnapshot,
    MemoryCyclePhase,
    MemoryCycleResult,
    MemoryCycleSourceSnapshot,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
)
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleOperation,
    MemoryCyclePhaseStatus,
    MemoryCycleStatus,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryRelationType
from app.shared.schemas.common_schemas import (
    StrictRootSchemaModel,
    StrictSchemaModel,
    described_field,
)

_IdempotencyKey = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=512),
]
_Sha256 = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=64,
        max_length=64,
        pattern="^[0-9a-f]{64}$",
    ),
]


class _MemoryCycleRequestFields(StrictSchemaModel):
    """Shared bounded source/window fields for both discriminated operations."""

    project: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=255),
        described_field("Required project identity for the cycle source window."),
    ]
    workspace_id: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=255),
        described_field("Optional workspace identity for the cycle source window."),
    ] = None
    scope: Annotated[
        ContextScope,
        described_field("Project scope for the cycle source window."),
    ] = ContextScope.PROJECT
    window_start: Annotated[
        datetime,
        described_field("Inclusive timezone-aware source window start."),
    ]
    window_end: Annotated[
        datetime,
        described_field("Inclusive timezone-aware source window end."),
    ]
    idempotency_key: Annotated[
        _IdempotencyKey,
        described_field("Stable logical identity used for cycle replay fencing."),
    ]
    max_contexts: Annotated[
        int,
        described_field("Maximum bounded Context candidates to scan.", ge=1, le=100),
    ] = 100

    @field_validator("window_start", "window_end")
    @classmethod
    def require_aware_datetime(cls, value: datetime) -> datetime:
        """Reject local/naive timestamps at the public boundary."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("memory-cycle window timestamps must be timezone-aware")
        return value

    @field_validator("window_end")
    @classmethod
    def require_ordered_window(
        cls,
        value: datetime,
        info: ValidationInfo,
    ) -> datetime:
        """Reject an end timestamp that precedes the start timestamp."""
        start = info.data.get("window_start")
        if isinstance(start, datetime) and value < start:
            raise ValueError("memory-cycle window_end must not precede window_start")
        return value

    @field_validator("scope")
    @classmethod
    def require_project_scope(cls, value: ContextScope) -> ContextScope:
        """Keep the public composite aligned with project CURRENT authority."""
        if ContextScope(value) is not ContextScope.PROJECT:
            raise ValueError("memory-cycle scope must be PROJECT")
        return value


class MemoryCycleDryRunRequestSchema(_MemoryCycleRequestFields):
    """Discriminated write-free memory-cycle planning request."""

    operation: Literal["dry_run"] = "dry_run"

    def to_command(self) -> MemoryCycleRequest:
        """Convert the boundary request to the typed application command."""
        return MemoryCycleRequest(
            operation=MemoryCycleOperation.DRY_RUN,
            project=self.project,
            workspace_id=self.workspace_id,
            scope=ContextScope(self.scope),
            window_start=self.window_start,
            window_end=self.window_end,
            idempotency_key=self.idempotency_key,
            max_contexts=self.max_contexts,
        )


class MemoryCycleApplyRequestSchema(_MemoryCycleRequestFields):
    """Discriminated fenced memory-cycle apply request."""

    operation: Literal["apply"] = "apply"
    expected_plan_hash: Annotated[
        _Sha256,
        described_field("Exact semantic plan hash admitted by a prior dry-run."),
    ]

    def to_command(self) -> MemoryCycleRequest:
        """Convert the boundary request to the typed application command."""
        return MemoryCycleRequest(
            operation=MemoryCycleOperation.APPLY,
            project=self.project,
            workspace_id=self.workspace_id,
            scope=ContextScope(self.scope),
            window_start=self.window_start,
            window_end=self.window_end,
            idempotency_key=self.idempotency_key,
            max_contexts=self.max_contexts,
            expected_plan_hash=self.expected_plan_hash,
        )


MemoryCycleRequestSchema = Annotated[
    MemoryCycleDryRunRequestSchema | MemoryCycleApplyRequestSchema,
    Field(discriminator="operation"),
]


class MemoryCycleRequestBody(StrictRootSchemaModel[MemoryCycleRequestSchema]):
    """Strict JSON-mode HTTP body wrapper for the cycle operation."""


class MemoryCycleSourceSnapshotResponse(StrictSchemaModel):
    """Stable source identity included in cycle plan provenance."""

    context_id: Annotated[str, described_field("Canonical Context identity.")]
    canonical_path: Annotated[str, described_field("Canonical source path.")]
    content_hash: Annotated[str, described_field("Canonical source content hash.")]
    source_revision: Annotated[
        str,
        described_field("Canonical source body and metadata revision."),
    ]

    @classmethod
    def from_entity(
        cls, value: MemoryCycleSourceSnapshot
    ) -> MemoryCycleSourceSnapshotResponse:
        """Map one source snapshot entity."""
        return cls(
            context_id=value.context_id,
            canonical_path=value.canonical_path,
            content_hash=value.content_hash,
            source_revision=value.source_revision,
        )


class MemoryCycleCompactSnapshotResponse(StrictSchemaModel):
    """Current Compact identity and provenance at plan time."""

    compact_id: Annotated[str, described_field("Current Compact identity.")]
    content_hash: Annotated[str, described_field("Current Compact body hash.")]
    source_set_hash: Annotated[
        str | None,
        described_field("Current Compact source-set hash."),
    ]
    status: Annotated[MemoryCompactStatus, described_field("Compact lifecycle status.")]

    @classmethod
    def from_entity(
        cls, value: MemoryCycleCompactSnapshot
    ) -> MemoryCycleCompactSnapshotResponse:
        """Map one Compact snapshot entity."""
        return cls(
            compact_id=value.compact_id,
            content_hash=value.content_hash,
            source_set_hash=value.source_set_hash,
            status=value.status,
        )


class MemoryCycleCandidateResponse(StrictSchemaModel):
    """Typed candidate bucket item."""

    context_id: Annotated[str, described_field("Candidate Context identity.")]
    title: Annotated[str, described_field("Candidate title.")]
    canonical_path: Annotated[str, described_field("Candidate source path.")]
    content_hash: Annotated[str, described_field("Candidate source content hash.")]
    relation: Annotated[
        MemoryRelationType | None,
        described_field("Selected existing reconciliation relation."),
    ]
    target_context_ids: Annotated[
        list[str],
        described_field("Existing Context targets considered by the plan."),
    ]
    child_plan_key: Annotated[
        str | None,
        described_field("Stable existing child-plan idempotency key."),
    ]
    reason: Annotated[str, described_field("Bounded relation explanation.")]
    requires_review: Annotated[
        bool,
        described_field("Whether explicit review is required before mutation."),
    ]

    @classmethod
    def from_entity(cls, value: MemoryCycleCandidate) -> MemoryCycleCandidateResponse:
        """Map one candidate entity."""
        return cls(
            context_id=value.context_id,
            title=value.title,
            canonical_path=value.canonical_path,
            content_hash=value.content_hash,
            relation=value.relation,
            target_context_ids=list(value.target_context_ids),
            child_plan_key=value.child_plan_key,
            reason=value.reason,
            requires_review=value.requires_review,
        )


class MemoryCycleCompactChangeResponse(StrictSchemaModel):
    """Compact publication candidate and verification state."""

    status: Annotated[
        MemoryCompactStatus | None,
        described_field("Candidate or persisted Compact lifecycle status."),
    ]
    compact_id: Annotated[str | None, described_field("Persisted Compact identity.")]
    content_hash: Annotated[str | None, described_field("Compact body hash.")]
    source_set_hash: Annotated[str | None, described_field("Compact source-set hash.")]
    review_verdict: Annotated[
        MemoryCompactReviewVerdict | None,
        described_field("Canonical Compact review verdict when available."),
    ]
    safe_to_publish: Annotated[
        bool,
        described_field("Whether existing Compact safety policy permits promotion."),
    ]
    warnings: Annotated[list[str], described_field("Compact safety warnings.")]

    @classmethod
    def from_entity(
        cls, value: MemoryCycleCompactChange
    ) -> MemoryCycleCompactChangeResponse:
        """Map one Compact change entity."""
        return cls(
            status=value.status,
            compact_id=value.compact_id,
            content_hash=value.content_hash,
            source_set_hash=value.source_set_hash,
            review_verdict=value.review_verdict,
            safe_to_publish=value.safe_to_publish,
            warnings=list(value.warnings),
        )


class MemoryCycleBucketsResponse(StrictSchemaModel):
    """All bounded candidate buckets returned by the cycle."""

    retained_facts: Annotated[
        list[MemoryCycleCandidateResponse], described_field("Retained facts.")
    ]
    duplicates: Annotated[
        list[MemoryCycleCandidateResponse], described_field("Duplicate candidates.")
    ]
    supersession_candidates: Annotated[
        list[MemoryCycleCandidateResponse], described_field("Supersession candidates.")
    ]
    contradictions: Annotated[
        list[MemoryCycleCandidateResponse], described_field("Contradiction candidates.")
    ]
    compact_changes: Annotated[
        list[MemoryCycleCompactChangeResponse], described_field("Compact changes.")
    ]
    summary_candidates: Annotated[
        list[MemoryCycleCandidateResponse], described_field("Summary candidates.")
    ]
    relationship_changes: Annotated[
        list[MemoryCycleCandidateResponse],
        described_field("Safe relationship changes."),
    ]
    archive_candidates: Annotated[
        list[MemoryCycleCandidateResponse], described_field("Archive candidates.")
    ]
    review_required: Annotated[
        list[MemoryCycleCandidateResponse],
        described_field("Review-required candidates."),
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

    child_plan_key: Annotated[str, described_field("Stable child plan key.")]
    plan_id: Annotated[str | None, described_field("Persisted child plan identity.")]
    result_id: Annotated[
        str | None, described_field("Persisted child result identity.")
    ]
    relation: Annotated[MemoryRelationType, described_field("Child relation.")]
    status: Annotated[str, described_field("Child lifecycle status.")]
    requires_review: Annotated[
        bool, described_field("Whether child review is required.")
    ]
    warnings: Annotated[list[str], described_field("Child warnings.")]
    affected_context_ids: Annotated[
        list[str],
        described_field("Canonical Context identities affected by the child."),
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

    name: Annotated[str, described_field("Phase name.")]
    status: Annotated[MemoryCyclePhaseStatus, described_field("Phase status.")]
    detail: Annotated[str, described_field("Bounded phase detail.")]
    warnings: Annotated[list[str], described_field("Phase warnings.")]

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

    operation: Annotated[MemoryCycleOperation, described_field("Cycle operation.")]
    status: Annotated[MemoryCycleStatus, described_field("Aggregate cycle status.")]
    idempotency_key: Annotated[str, described_field("Cycle idempotency key.")]
    plan_hash: Annotated[str, described_field("Deterministic semantic plan hash.")]
    project: Annotated[str, described_field("Project identity.")]
    workspace_id: Annotated[str | None, described_field("Workspace identity.")]
    scope: Annotated[str | None, described_field("Strict Context scope.")]
    window_start: Annotated[datetime, described_field("Window start.")]
    window_end: Annotated[datetime, described_field("Window end.")]
    replayed: Annotated[
        bool, described_field("Whether a verified checkpoint was replayed.")
    ]
    scanned: Annotated[int, described_field("Contexts scanned.")]
    total_available: Annotated[int, described_field("Total matching Contexts.")]
    candidate_count: Annotated[int, described_field("Bounded candidate count.")]
    source_snapshot: Annotated[
        list[MemoryCycleSourceSnapshotResponse], described_field("Source provenance.")
    ]
    current_compact: Annotated[
        MemoryCycleCompactSnapshotResponse | None,
        described_field("Current Compact planning snapshot."),
    ]
    buckets: Annotated[
        MemoryCycleBucketsResponse, described_field("Typed cycle buckets.")
    ]
    child_outcomes: Annotated[
        list[MemoryCycleChildOutcomeResponse], described_field("Child plan outcomes.")
    ]
    compact_change: Annotated[
        MemoryCycleCompactChangeResponse | None,
        described_field("Compact publication outcome."),
    ]
    phases: Annotated[
        list[MemoryCyclePhaseResponse], described_field("Phase evidence.")
    ]
    warnings: Annotated[list[str], described_field("Aggregate warnings.")]
    elapsed_ms: Annotated[
        float, described_field("Observed cycle latency in milliseconds.")
    ]
    query_count: Annotated[
        int | None, described_field("Measured query count when instrumented.")
    ]
    hard_delete_performed: Annotated[
        bool, described_field("Whether any hard delete occurred.")
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
