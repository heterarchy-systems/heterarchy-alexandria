"""Bounded dry-run and safe backfill for existing durable Context memory."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from app.memory.application.contexts.records.context_service_ports import (
    ContextListPort,
)
from app.memory.application.reconciliation.candidates.memory_candidate_recall_service import (
    MemoryCandidateRecallService,
)
from app.memory.application.reconciliation.candidates.memory_candidate_service import (
    MemoryCandidateService,
)
from app.memory.application.reconciliation.candidates.memory_relation_classifier import (
    MemoryRelationClassifier,
)
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    temporal_state_from_context_metadata,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_plan_service import (
    MemoryReconciliationPlanService,
)
from app.memory.domain.contracts.memory_existing_reconciliation_contracts import (
    ExistingMemoryReconciliationRequest,
)
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryCandidateCreate,
)
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.entities.memory_existing_reconciliation import (
    ExistingMemoryAssessment,
    ExistingMemoryPlanPreview,
    ExistingMemoryPlanPreviewReport,
    ExistingMemoryReconciliationReport,
)
from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    MemoryCandidate,
    MemoryRecallCandidate,
    MemoryReconciliationPlan,
    MemorySourceReference,
    MemoryTemporalState,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryRelationType
from app.memory.domain.repositories.reconciliation.memory_reconciliation_use_case_repositories import (
    IMemoryExistingReconciliationRepository,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.serialization.orjson_codec import loads_json
from app.shared.types.extra_types import JSONValue

_CLAIMS_ADAPTER = TypeAdapter(tuple[CanonicalClaim, ...])


class MemoryExistingReconciliationService:
    """Analyze existing memory and backfill only missing reconciliation read models."""

    def __init__(
        self,
        context_service: ContextListPort,
        candidate_service: MemoryCandidateService,
        recall_service: MemoryCandidateRecallService,
        classifier: MemoryRelationClassifier,
        plan_service: MemoryReconciliationPlanService,
        repository: IMemoryExistingReconciliationRepository,
    ) -> None:
        """Initialize MemoryExistingReconciliationService state and dependencies.

        Args:
            context_service: Context service dependency.
            candidate_service: Candidate service dependency.
            recall_service: Recall service dependency.
            classifier: Classifier used by this operation.
            plan_service: Plan service dependency.
            repository: Repository used by this operation.
        """
        self._context_service = context_service
        self._candidate_service = candidate_service
        self._recall_service = recall_service
        self._classifier = classifier
        self._plan_service = plan_service
        self._repository = repository

    async def preview(
        self,
        request: ExistingMemoryReconciliationRequest,
    ) -> ExistingMemoryReconciliationReport:
        """Analyze existing memory without writing plans or temporal overlays.

        Args:
            request: Request.

        Returns:
            ExistingMemoryReconciliationReport: Operation result.
        """
        return await self._run(request, dry_run=True)

    async def apply(
        self,
        request: ExistingMemoryReconciliationRequest,
    ) -> ExistingMemoryReconciliationReport:
        """Backfill missing overlays and persist reviewable plans idempotently.

        Args:
            request: Request.

        Returns:
            ExistingMemoryReconciliationReport: Operation result.
        """
        return await self._run(request, dry_run=False)

    async def preview_plans(
        self,
        request: ExistingMemoryReconciliationRequest,
    ) -> ExistingMemoryPlanPreviewReport:
        """Return full child plans without persisting plans or temporal overlays.

        This is the read-only planning surface used by aggregate memory-cycle
        orchestration.  It deliberately shares candidate construction,
        retrieval, classification, and plan policy with the existing-memory
        reconciliation owner instead of reimplementing those semantics.

        Args:
            request: Existing-memory scan filters and bounds.

        Returns:
            Bounded full child-plan preview.
        """
        _validate_request(request)
        previews: list[ExistingMemoryPlanPreview] = []
        warnings: list[str] = []
        scanned = 0
        total_available = 0
        offset = 0
        while scanned < request.max_contexts:
            page_limit = min(request.batch_size, request.max_contexts - scanned)
            contexts, total = await self._list_contexts_page(
                request,
                limit=page_limit,
                offset=offset,
            )
            total_available = total
            if not contexts:
                break
            for context in contexts:
                prepared = await self._prepare_context(context, request)
                previews.append(
                    ExistingMemoryPlanPreview(
                        context=context,
                        content_hash=prepared.candidate.content_hash,
                        canonical_path=prepared.canonical_path,
                        temporal=prepared.temporal,
                        temporal_overlay_present=prepared.temporal_overlay_present,
                        plan=prepared.plan,
                        warnings=prepared.warnings,
                        compared_contexts=prepared.recalled,
                    )
                )
            scanned += len(contexts)
            offset += len(contexts)
            if offset >= total:
                break
        if total_available > scanned:
            warnings.append(
                f"Scan stopped at max_contexts={request.max_contexts}; "
                f"{total_available - scanned} matching Contexts remain."
            )
        warnings.append(
            "Dry-run child-plan preview completed without persisting plans or "
            "temporal overlays."
        )
        return ExistingMemoryPlanPreviewReport(
            scanned=scanned,
            total_available=total_available,
            window_start=request.created_after,
            window_end=request.created_before,
            previews=tuple(previews),
            warnings=tuple(warnings),
        )

    async def _run(
        self,
        request: ExistingMemoryReconciliationRequest,
        dry_run: bool,
    ) -> ExistingMemoryReconciliationReport:
        """Execute run.

        Args:
            request: Validated request for this operation.
            dry_run: Dry run used by this operation.

        Returns:
            ExistingMemoryReconciliationReport result produced by run.
        """
        _validate_request(request)
        assessments: list[ExistingMemoryAssessment] = []
        warnings: list[str] = []
        scanned = 0
        total_available = 0
        temporal_backfill_candidates = 0
        temporal_states_written = 0
        plans_generated = 0
        plans_persisted = 0
        contexts_missing_claims = 0
        review_required = 0
        offset = 0
        while scanned < request.max_contexts:
            page_limit = min(request.batch_size, request.max_contexts - scanned)
            contexts, total = await self._list_contexts_page(
                request,
                limit=page_limit,
                offset=offset,
            )
            total_available = total
            if not contexts:
                break
            for context in contexts:
                assessment, counters = await self._assess_context(
                    context,
                    request=request,
                    dry_run=dry_run,
                )
                assessments.append(assessment)
                temporal_backfill_candidates += counters.temporal_backfill_candidates
                temporal_states_written += counters.temporal_states_written
                plans_generated += counters.plans_generated
                plans_persisted += counters.plans_persisted
                contexts_missing_claims += counters.contexts_missing_claims
                review_required += counters.review_required
            scanned += len(contexts)
            offset += len(contexts)
            if offset >= total:
                break
        if total_available > scanned:
            warnings.append(
                f"Scan stopped at max_contexts={request.max_contexts}; "
                f"{total_available - scanned} matching Contexts remain."
            )
        if dry_run:
            warnings.append(
                "Dry-run completed without persisting plans or temporal overlays."
            )
        return ExistingMemoryReconciliationReport(
            dry_run=dry_run,
            scanned=scanned,
            total_available=total_available,
            temporal_backfill_candidates=temporal_backfill_candidates,
            temporal_states_written=temporal_states_written,
            plans_generated=plans_generated,
            plans_persisted=plans_persisted,
            contexts_missing_claims=contexts_missing_claims,
            review_required=review_required,
            assessments=tuple(assessments),
            warnings=tuple(warnings),
            hard_delete_performed=False,
        )

    async def _assess_context(
        self,
        context: ContextRecord,
        request: ExistingMemoryReconciliationRequest,
        dry_run: bool,
    ) -> tuple[ExistingMemoryAssessment, _AssessmentCounters]:
        """Execute assess context.

        Args:
            context: Context used by this operation.
            request: Validated request for this operation.
            dry_run: Dry run used by this operation.

        Returns:
            tuple[ExistingMemoryAssessment, _AssessmentCounters] result produced by assess context.
        """
        prepared = await self._prepare_context(context, request)
        temporal = prepared.temporal
        backfill_required = not prepared.temporal_overlay_present
        temporal_states_written = 0
        if backfill_required and not dry_run:
            await self._repository.upsert_temporal_state(temporal)
            temporal_states_written = 1
        plan_id: str | None = None
        plan_persisted = False
        primary_relation: MemoryRelationType | None = None
        requires_review = False
        if prepared.plan is not None:
            plan = prepared.plan
            plans_generated = 1
            primary_relation = plan.primary_decision
            requires_review = plan.requires_review
            if dry_run:
                plan_id = plan.plan_id
            else:
                existing_plan = await self._repository.get_plan_by_idempotency_key(
                    plan.idempotency_key
                )
                persisted_plan = (
                    existing_plan
                    if existing_plan is not None
                    else await self._repository.save_plan(plan)
                )
                plan_id = persisted_plan.plan_id
                plan_persisted = existing_plan is None
        else:
            plans_generated = 0
        assessment = ExistingMemoryAssessment(
            context_id=context.id,
            temporal_overlay_present=prepared.temporal_overlay_present,
            temporal_backfill_required=backfill_required,
            canonical_claim_count=len(prepared.candidate.canonical_claims),
            primary_relation=primary_relation,
            related_context_ids=tuple(
                dict.fromkeys(
                    decision.existing_context_id for decision in prepared.plan.decisions
                )
                if prepared.plan is not None
                else ()
            ),
            plan_id=plan_id,
            plan_persisted=plan_persisted,
            requires_review=requires_review,
            warnings=prepared.warnings,
        )
        return assessment, _AssessmentCounters(
            temporal_backfill_candidates=int(backfill_required),
            temporal_states_written=temporal_states_written,
            plans_generated=plans_generated,
            plans_persisted=int(plan_persisted),
            contexts_missing_claims=int(not prepared.candidate.canonical_claims),
            review_required=int(requires_review),
        )

    async def _list_contexts_page(
        self,
        request: ExistingMemoryReconciliationRequest,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ContextRecord], int]:
        """List one page while preserving the original minimal port call shape."""
        if (
            request.workspace_id is None
            and request.created_after is None
            and request.created_before is None
        ):
            return await self._context_service.list_contexts(
                limit=limit,
                offset=offset,
                project=request.project,
                scope=request.scope,
                include_archived=request.include_archived,
            )
        return await self._context_service.list_contexts(
            limit=limit,
            offset=offset,
            project=request.project,
            scope=request.scope,
            workspace_id=request.workspace_id,
            include_archived=request.include_archived,
            created_after=request.created_after,
            created_before=request.created_before,
        )

    async def _prepare_context(
        self,
        context: ContextRecord,
        request: ExistingMemoryReconciliationRequest,
    ) -> _PreparedContext:
        """Build one candidate and child plan without persistence effects."""
        persisted_temporal = await self._repository.get_temporal_state(context.id)
        canonical_temporal = temporal_state_from_context_metadata(context)
        temporal = (
            persisted_temporal or canonical_temporal or _default_temporal(context)
        )
        claims = _canonical_claims(context.context_metadata)
        warnings: list[str] = []
        if not claims:
            warnings.append("canonical_claims_unavailable")
        if persisted_temporal is None and canonical_temporal is None:
            warnings.append("temporal_metadata_unavailable_recorded_at_only")
        candidate = self._candidate_service.create(
            _candidate_payload(context, temporal=temporal, claims=claims)
        )
        recalled = await self._recall_service.recall(
            candidate,
            limit=request.recall_limit,
        )
        decisions = tuple(
            [
                await self._classifier.classify_with_model(candidate, existing)
                for existing in recalled
                if existing.context_id != context.id
            ]
        )
        meaningful = tuple(
            decision
            for decision in decisions
            if decision.relation is not MemoryRelationType.UNRELATED
        )
        plan = (
            self._plan_service.build(
                candidate=candidate,
                decisions=meaningful,
                idempotency_key=_existing_plan_key(context.id, candidate.content_hash),
            )
            if meaningful
            else None
        )
        return _PreparedContext(
            candidate=candidate,
            canonical_path=_canonical_path(context),
            temporal=temporal,
            temporal_overlay_present=persisted_temporal is not None,
            plan=plan,
            warnings=tuple(warnings),
            recalled=recalled,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class _AssessmentCounters:
    """Small immutable counter bundle used inside one scan iteration."""

    temporal_backfill_candidates: int
    temporal_states_written: int
    plans_generated: int
    plans_persisted: int
    contexts_missing_claims: int
    review_required: int


@dataclass(frozen=True, slots=True, kw_only=True)
class _PreparedContext:
    """Read-only candidate and plan evidence shared by scan operations."""

    candidate: MemoryCandidate
    canonical_path: str
    temporal: MemoryTemporalState
    temporal_overlay_present: bool
    plan: MemoryReconciliationPlan | None
    warnings: tuple[str, ...]
    recalled: tuple[MemoryRecallCandidate, ...]


def _validate_request(request: ExistingMemoryReconciliationRequest) -> None:
    """Validate request.

    Args:
        request: Validated request for this operation.
    """
    if request.max_contexts < 1 or request.max_contexts > 10_000:
        raise MemoryContextValidationError(
            "existing-memory max_contexts must be between 1 and 10000"
        )
    if request.batch_size < 1 or request.batch_size > 500:
        raise MemoryContextValidationError(
            "existing-memory batch_size must be between 1 and 500"
        )
    if request.recall_limit < 1 or request.recall_limit > 100:
        raise MemoryContextValidationError(
            "existing-memory recall_limit must be between 1 and 100"
        )
    if request.created_after is not None and request.created_after.tzinfo is None:
        raise MemoryContextValidationError(
            "existing-memory created_after must be timezone-aware"
        )
    if request.created_before is not None and request.created_before.tzinfo is None:
        raise MemoryContextValidationError(
            "existing-memory created_before must be timezone-aware"
        )
    if (
        request.created_after is not None
        and request.created_before is not None
        and request.created_before < request.created_after
    ):
        raise MemoryContextValidationError(
            "existing-memory created_before must not be before created_after"
        )


def _default_temporal(context: ContextRecord) -> MemoryTemporalState:
    """Execute default temporal.

    Args:
        context: Context used by this operation.

    Returns:
        MemoryTemporalState result produced by default temporal.
    """
    return MemoryTemporalState(
        context_id=context.id,
        recorded_at=context.created_at,
        observed_at=None,
        valid_from=None,
        valid_to=None,
        is_current=not context.is_archived,
        conflict_set_ids=(),
        superseded_by=(),
        supersedes=(),
        relation_summary=(),
    )


def _candidate_payload(
    context: ContextRecord,
    temporal: MemoryTemporalState,
    claims: tuple[CanonicalClaim, ...],
) -> MemoryCandidateCreate:
    """Execute candidate payload.

    Args:
        context: Context used by this operation.
        temporal: Temporal used by this operation.
        claims: Claims used by this operation.

    Returns:
        MemoryCandidateCreate result produced by candidate payload.
    """
    metadata = context.context_metadata
    content_hash = (
        _metadata_text(metadata, "content_hash")
        or hashlib.sha256(context.content.encode("utf-8")).hexdigest()
    )
    detail_path = _metadata_text(metadata, "relative_path") or f"context:{context.id}"
    source_ref = MemorySourceReference(
        source_type=context.source_type.value,
        source_id=context.id,
        title=context.title,
        detail_path=detail_path,
        source_hash=content_hash,
        observed_at=temporal.observed_at,
    )
    return MemoryCandidateCreate(
        title=context.title,
        body=context.content,
        scope=context.scope,
        project=context.project,
        workspace_id=context.workspace_id,
        agent_id=context.agent_id,
        user_id=context.user_id,
        session_id=context.session_id,
        canonical_claims=claims,
        tags=tuple(context.tags),
        source_refs=(source_ref,),
        recorded_at=temporal.recorded_at,
        observed_at=temporal.observed_at,
        valid_from=temporal.valid_from,
        valid_to=temporal.valid_to,
        requested_lifecycle="archived" if context.is_archived else "active",
        candidate_id=f"existing:{context.id}",
        source_identity=_metadata_text(metadata, "source"),
        lineage_ancestors=tuple(sorted(set(temporal.supersedes))),
    )


def _canonical_claims(metadata: ContextMetadataPayload) -> tuple[CanonicalClaim, ...]:
    """Execute canonical claims.

    Args:
        metadata: Metadata used by this operation.

    Returns:
        tuple[CanonicalClaim, ...] result produced by canonical claims.
    """
    value: JSONValue | None = metadata.get("canonical_claims")
    if isinstance(value, str):
        try:
            value = loads_json(value)
        except (TypeError, ValueError):
            return ()
    if not isinstance(value, list):
        return ()
    try:
        return _CLAIMS_ADAPTER.validate_python(value)
    except ValidationError:
        return ()


def _metadata_text(metadata: ContextMetadataPayload, key: str) -> str | None:
    """Execute metadata text.

    Args:
        metadata: Metadata used by this operation.
        key: Key used by this operation.

    Returns:
        str | None result produced by metadata text.
    """
    value: JSONValue | None = metadata.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _canonical_path(context: ContextRecord) -> str:
    """Return the canonical source path used by cycle identity evidence."""
    return _metadata_text(context.context_metadata, "relative_path") or (
        f"context:{context.id}"
    )


def _existing_plan_key(context_id: str, content_hash: str) -> str:
    """Execute existing plan key.

    Args:
        context_id: Identifier for context.
        content_hash: Content hash used by this operation.

    Returns:
        str result produced by existing plan key.
    """
    return f"existing-memory:{context_id}:{content_hash}"
