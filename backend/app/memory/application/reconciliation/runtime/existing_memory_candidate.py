"""Prepare existing durable Contexts as bounded reconciliation candidates."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

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
from app.shared.serialization.orjson_codec import loads_json
from app.shared.types.extra_types import JSONValue

_CLAIMS_ADAPTER = TypeAdapter(tuple[CanonicalClaim, ...])


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedExistingMemoryContext:
    """Candidate evidence shared by one existing-memory scan iteration."""

    candidate: MemoryCandidate
    canonical_path: str
    temporal: MemoryTemporalState
    temporal_overlay_present: bool
    plan: MemoryReconciliationPlan | None
    warnings: tuple[str, ...]
    recalled: tuple[MemoryRecallCandidate, ...]


class ExistingMemoryCandidatePolicy:
    """Build candidate and source evidence from stored Context records."""

    @staticmethod
    def default_temporal(context: ContextRecord) -> MemoryTemporalState:
        """Use the Context creation time when no temporal overlay exists.

        Args:
            context: Stored Context record used for reconciliation.

        Returns:
            Temporal state without inferred observation or validity dates.
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

    @staticmethod
    def candidate_payload(
        context: ContextRecord,
        temporal: MemoryTemporalState,
        claims: tuple[CanonicalClaim, ...],
    ) -> MemoryCandidateCreate:
        """Map one Context record and its canonical evidence into a candidate.

        Args:
            context: Stored Context record being classified.
            temporal: Existing or derived temporal state for the record.
            claims: Canonical claims successfully parsed from stored metadata.

        Returns:
            Candidate creation request preserving stored provenance fields.
        """
        metadata = context.context_metadata
        content_hash = (
            ExistingMemoryCandidatePolicy.metadata_text(metadata, "content_hash")
            or hashlib.sha256(context.content.encode("utf-8")).hexdigest()
        )
        detail_path = (
            ExistingMemoryCandidatePolicy.metadata_text(metadata, "relative_path")
            or f"context:{context.id}"
        )
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
            source_identity=ExistingMemoryCandidatePolicy.metadata_text(
                metadata, "source"
            ),
            lineage_ancestors=tuple(sorted(set(temporal.supersedes))),
        )

    @staticmethod
    def canonical_claims(
        metadata: ContextMetadataPayload,
    ) -> tuple[CanonicalClaim, ...]:
        """Read claims leniently from legacy or current Context metadata.

        Args:
            metadata: Stored Context metadata, including legacy JSON text values.

        Returns:
            Parsed claims, or an empty tuple when stored claims are absent or invalid.
        """
        value: JSONValue | None = metadata.get("canonical_claims")
        if isinstance(value, str):
            try:
                value = loads_json(value)
            except TypeError, ValueError:
                return ()
        if not isinstance(value, list):
            return ()
        try:
            return _CLAIMS_ADAPTER.validate_python(value)
        except ValidationError:
            return ()

    @staticmethod
    def metadata_text(metadata: ContextMetadataPayload, key: str) -> str | None:
        """Read one nonblank text field from stored Context metadata.

        Args:
            metadata: Stored metadata mapping.
            key: Metadata field to read.

        Returns:
            Trimmed text or None for missing, non-string, or blank values.
        """
        value: JSONValue | None = metadata.get(key)
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def canonical_path(context: ContextRecord) -> str:
        """Return the source path used for reconciliation identity evidence.

        Args:
            context: Stored Context record being reconciled.

        Returns:
            Stored relative path or its existing context-id fallback.
        """
        return (
            ExistingMemoryCandidatePolicy.metadata_text(
                context.context_metadata, "relative_path"
            )
            or f"context:{context.id}"
        )

    @staticmethod
    def existing_plan_key(context_id: str, content_hash: str) -> str:
        """Build the stable idempotency key for one existing Context plan.

        Args:
            context_id: Existing Context identifier.
            content_hash: Canonical candidate content hash.

        Returns:
            Existing-memory plan idempotency key.
        """
        return f"existing-memory:{context_id}:{content_hash}"


class ExistingMemoryCandidatePreparer:
    """Load and classify one existing Context without persistence writes."""

    def __init__(
        self,
        candidate_service: MemoryCandidateService,
        recall_service: MemoryCandidateRecallService,
        classifier: MemoryRelationClassifier,
        plan_service: MemoryReconciliationPlanService,
        repository: IMemoryExistingReconciliationRepository,
    ) -> None:
        """Bind the existing reconciliation capabilities for candidate preparation.

        Args:
            candidate_service: Existing candidate construction owner.
            recall_service: Existing bounded candidate recall owner.
            classifier: Existing relation classification owner.
            plan_service: Existing deterministic plan builder.
            repository: Existing temporal read-only reconciliation port.
        """
        self._candidate_service = candidate_service
        self._recall_service = recall_service
        self._classifier = classifier
        self._plan_service = plan_service
        self._repository = repository

    async def prepare(
        self,
        context: ContextRecord,
        request: ExistingMemoryReconciliationRequest,
    ) -> PreparedExistingMemoryContext:
        """Build candidate and plan evidence without persistence effects.

        Args:
            context: Stored Context record being assessed.
            request: Bounds and filters for the enclosing scan.

        Returns:
            Prepared candidate, temporal state, recall, and optional child plan.
        """
        persisted_temporal = await self._repository.get_temporal_state(context.id)
        canonical_temporal = temporal_state_from_context_metadata(context)
        temporal = (
            persisted_temporal
            or canonical_temporal
            or ExistingMemoryCandidatePolicy.default_temporal(context)
        )
        claims = ExistingMemoryCandidatePolicy.canonical_claims(
            context.context_metadata
        )
        warnings: list[str] = []
        if not claims:
            warnings.append("canonical_claims_unavailable")
        if persisted_temporal is None and canonical_temporal is None:
            warnings.append("temporal_metadata_unavailable_recorded_at_only")
        candidate = self._candidate_service.create(
            ExistingMemoryCandidatePolicy.candidate_payload(
                context, temporal=temporal, claims=claims
            )
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
                idempotency_key=ExistingMemoryCandidatePolicy.existing_plan_key(
                    context.id, candidate.content_hash
                ),
            )
            if meaningful
            else None
        )
        return PreparedExistingMemoryContext(
            candidate=candidate,
            canonical_path=ExistingMemoryCandidatePolicy.canonical_path(context),
            temporal=temporal,
            temporal_overlay_present=persisted_temporal is not None,
            plan=plan,
            warnings=tuple(warnings),
            recalled=recalled,
        )
