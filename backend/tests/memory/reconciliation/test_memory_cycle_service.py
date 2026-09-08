"""Focused aggregate memory-cycle behavior tests."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.memory.application.reconciliation.candidates.memory_candidate_service import (
    MemoryCandidateService,
)
from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_policy import (
    MemoryCompactReconciliationPolicy,
)
from app.memory.application.reconciliation.cycles.memory_cycle_service import (
    MemoryCycleService,
)
from app.memory.application.reconciliation.cycles.memory_cycle_source_fence import (
    MemoryCycleSourceFence,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_plan_service import (
    MemoryReconciliationPlanService,
)
from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryCandidateCreate,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextPack,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)
from app.memory.domain.entities.memory_existing_reconciliation import (
    ExistingMemoryPlanPreview,
    ExistingMemoryPlanPreviewReport,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryRelationDecision,
    MemoryRelationScores,
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
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleOperation,
    MemoryCycleStatus,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryDecisionSource,
    MemoryRelationType,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactNotFoundError
from app.shared.exceptions.memory_cycle_exceptions import MemoryCycleStalePlanError
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
)
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.types.types_convert_utils import now_utc

NOW = datetime(2026, 9, 8, tzinfo=UTC)


class _ExistingPreview:
    """Return one deterministic read-only existing-memory preview."""

    def __init__(self, preview: ExistingMemoryPlanPreview) -> None:
        self.preview = preview

    async def preview_plans(
        self,
        request: object,
    ) -> ExistingMemoryPlanPreviewReport:
        """Return the prebuilt plan without persistence effects."""
        _ = request
        return ExistingMemoryPlanPreviewReport(
            scanned=1,
            total_available=1,
            window_start=None,
            window_end=None,
            previews=(self.preview,),
            warnings=(),
        )


class _RetrievalSearch:
    """Return the selected source through one bounded retrieval canary."""

    def __init__(self, context: ContextRecord) -> None:
        self.context = context

    async def search(self, **kwargs: object) -> ContextPack:
        """Return one deterministic post-apply retrieval match."""
        _ = kwargs
        chunk = ContextChunkRecord(
            id="chunk-1",
            context_id=self.context.id,
            chunk_index=0,
            heading=None,
            content=self.context.content,
            token_count=8,
            content_hash="chunk-hash",
            chunk_metadata={},
            created_at=self.context.created_at,
        )
        return ContextPack(
            query=self.context.title,
            strategy=RagStrategy.HYBRID,
            effective_strategy=RagStrategy.HYBRID,
            warnings=(),
            recall_scopes=(ContextScope.PROJECT,),
            matches=(
                ContextSearchMatch(
                    context=self.context,
                    chunk=chunk,
                    score=1.0,
                    fts_score=1.0,
                    vector_score=1.0,
                    why_retrieved="test canary",
                ),
            ),
            context_pack=self.context.content,
        )


class _CanonicalSource:
    """Unused in SQL-owned unit fixtures; Obsidian IDs are absent by design."""

    async def read_note(self, note_id: str) -> object:
        """Fail if a fixture unexpectedly selects an Obsidian source."""
        raise AssertionError(f"unexpected Obsidian source read: {note_id}")


class _ContextSource:
    """Return the current SQL-owned Context for source-fence unit tests."""

    def __init__(self, context: ContextRecord) -> None:
        self.context = context

    async def get(self, context_id: str) -> ContextRecord:
        """Return the one fixture Context."""
        assert context_id == self.context.id
        return self.context


class _ReconciliationRepository:
    """Small in-memory child plan/result authority for service tests."""

    def __init__(self) -> None:
        self.plans: dict[str, object] = {}
        self.results: dict[str, object] = {}

    async def get_plan_by_idempotency_key(self, key: str) -> object | None:
        """Return one plan by stable key."""
        return next(
            (plan for plan in self.plans.values() if plan.idempotency_key == key),
            None,
        )

    async def save_plan(self, plan: object) -> object:
        """Persist one child plan by its immutable identity."""
        self.plans[plan.plan_id] = plan
        return plan

    async def get_plan(self, plan_id: str) -> object | None:
        """Return one plan by id."""
        return self.plans.get(plan_id)

    async def get_result(self, result_id: str) -> object | None:
        """Return one child result by id."""
        return self.results.get(result_id)


class _ApplyService:
    """Guard against accidental auto-approval in review-bound tests."""

    calls = 0

    async def apply(self, plan_id: str) -> object:
        """Fail if an unsafe review plan reaches apply."""
        self.calls += 1
        raise AssertionError(f"review-bound plan was auto-applied: {plan_id}")


class _CompactService:
    """File-backed Compact lifecycle double with one CURRENT invariant."""

    def __init__(self) -> None:
        self.items: dict[str, MemoryCompact] = {}
        self.current_item: MemoryCompact | None = None
        self.create_count = 0
        self.mark_current_count = 0

    async def current(self, project: str | None = None) -> MemoryCompact:
        """Return current Compact or the canonical not-found error."""
        if self.current_item is None or self.current_item.project != project:
            raise MemoryCompactNotFoundError("no current Compact")
        return self.current_item

    async def create(self, payload: object) -> MemoryCompact:
        """Create one draft Compact."""
        self.create_count += 1
        compact_id = f"compact-{self.create_count}"
        source_refs = tuple(
            MemoryCompactSourceRef(
                id=new_uuid(),
                compact_id=compact_id,
                source_type=source_ref.source_type,
                source_id=source_ref.source_id,
                title=source_ref.title,
                detail_path=source_ref.detail_path,
                source_hash=source_ref.source_hash,
            )
            for source_ref in payload.source_refs
        )
        compact = MemoryCompact(
            id=compact_id,
            project=payload.project,
            covered_from=payload.covered_from,
            covered_to=payload.covered_to,
            markdown_body=payload.markdown_body,
            status=payload.status,
            source_refs=source_refs,
            created_at=NOW,
            updated_at=NOW,
            archived_at=None,
            source_set_hash="source-set-hash",
        )
        self.items[compact_id] = compact
        return compact

    async def mark_current(self, compact_id: str) -> MemoryCompact:
        """Promote one draft Compact to CURRENT."""
        self.mark_current_count += 1
        compact = replace(self.items[compact_id], status=MemoryCompactStatus.CURRENT)
        self.items[compact_id] = compact
        self.current_item = compact
        return compact

    async def list_compacts(self, **kwargs: object) -> tuple[list[MemoryCompact], int]:
        """Return the project CURRENT set."""
        _ = kwargs
        values = [] if self.current_item is None else [self.current_item]
        return values, len(values)

    async def get(self, compact_id: str) -> MemoryCompact:
        """Read one Compact by id."""
        return self.items[compact_id]


async def _noop() -> None:
    """No-op transaction callback for an isolated service test."""


def _context() -> ContextRecord:
    """Build one source Context with explicit source provenance."""
    return ContextRecord(
        id="context-1",
        kind=ContextKind.DECISION,
        title="Safe authority decision",
        summary="PostgreSQL is authoritative.",
        content="PostgreSQL is the durable authority for indexed memory.",
        content_format=ContextContentFormat.MARKDOWN,
        project="project-a",
        scope=ContextScope.PROJECT,
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="test",
        source_type=ContextSourceType.USER,
        importance=ContextImportance.HIGH,
        tags=(),
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=(),
        restore_prompt=None,
        context_metadata={"relative_path": "project-a/decision.md"},
        created_at=NOW - timedelta(days=1),
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )


def _preview(plan: object | None = None) -> ExistingMemoryPlanPreview:
    """Build one existing-memory child preview."""
    context = _context()
    return ExistingMemoryPlanPreview(
        context=context,
        content_hash=hash_text(context.content),
        canonical_path="project-a/decision.md",
        temporal=MemoryTemporalState(
            context_id=context.id,
            recorded_at=context.created_at,
            observed_at=None,
            valid_from=None,
            valid_to=None,
            is_current=True,
        ),
        temporal_overlay_present=True,
        plan=plan,
        warnings=(),
    )


def _service(
    tmp_path: Path,
    preview: ExistingMemoryPlanPreview,
) -> tuple[
    MemoryCycleService, _CompactService, _ReconciliationRepository, _ApplyService
]:
    """Construct one cycle service over explicit fakes and real checkpoint storage."""
    repository = _ReconciliationRepository()
    apply_service = _ApplyService()
    compact_service = _CompactService()
    service = MemoryCycleService(
        existing_reconciliation_service=_ExistingPreview(preview),
        context_service=_RetrievalSearch(preview.context),
        source_fence=MemoryCycleSourceFence(
            source=_CanonicalSource(),
            context_reader=_ContextSource(preview.context),
        ),
        reconciliation_repository=repository,
        reconciliation_apply_service=apply_service,
        compact_service=compact_service,
        compact_policy=MemoryCompactReconciliationPolicy(),
        index_maintenance_coordinator=IndexMaintenanceCoordinator(),
        checkpoint_store=ObsidianReportBundleRunStore(tmp_path),
        commit_projection=_noop,
        rollback_projection=_noop,
    )
    return service, compact_service, repository, apply_service


def _request(operation: MemoryCycleOperation, **kwargs: object) -> MemoryCycleRequest:
    """Build one bounded project-window request."""
    return MemoryCycleRequest(
        operation=operation,
        project="project-a",
        window_start=NOW - timedelta(days=2),
        window_end=NOW,
        idempotency_key="cycle-test",
        max_contexts=100,
        **kwargs,
    )


def test_memory_cycle_dry_run_is_write_free(tmp_path: Path) -> None:
    """Dry-run computes a deterministic plan without child/Compact/checkpoint writes."""

    async def scenario() -> None:
        service, compact, repository, _ = _service(tmp_path, _preview())

        result = await service.execute(_request(MemoryCycleOperation.DRY_RUN))

        assert result.status is MemoryCycleStatus.PREVIEW
        assert result.plan_hash
        assert compact.create_count == 0
        assert repository.plans == {}
        assert not (tmp_path / ".alexandria" / "report-bundle-runs").exists()

    asyncio.run(scenario())


def test_memory_cycle_apply_clean_fixture_replays_after_restart(tmp_path: Path) -> None:
    """A safe cycle creates one CURRENT Compact and replay reuses its checkpoint."""

    async def scenario() -> None:
        service, compact, _, _ = _service(tmp_path, _preview())
        preview = await service.execute(_request(MemoryCycleOperation.DRY_RUN))
        applied = await service.execute(
            _request(
                MemoryCycleOperation.APPLY,
                expected_plan_hash=preview.plan_hash,
            )
        )
        replayed = await service.execute(
            _request(
                MemoryCycleOperation.APPLY,
                expected_plan_hash=preview.plan_hash,
            )
        )

        assert applied.status is MemoryCycleStatus.APPLIED
        assert applied.compact_change is not None
        assert applied.compact_change.status is MemoryCompactStatus.CURRENT
        assert compact.create_count == 1
        assert compact.mark_current_count == 1
        assert replayed.replayed is True
        assert compact.create_count == 1

    asyncio.run(scenario())


def test_memory_cycle_stale_plan_rejects_before_mutation(tmp_path: Path) -> None:
    """Apply rejects a mismatched plan hash before any canonical effect."""

    async def scenario() -> None:
        service, compact, repository, _ = _service(tmp_path, _preview())

        with pytest.raises(MemoryCycleStalePlanError):
            await service.execute(
                _request(
                    MemoryCycleOperation.APPLY,
                    expected_plan_hash="0" * 64,
                )
            )

        assert compact.create_count == 0
        assert repository.plans == {}

    asyncio.run(scenario())


def test_memory_cycle_contradiction_stays_review_bound(tmp_path: Path) -> None:
    """Contradiction plans remain review-required and never auto-apply."""

    async def scenario() -> None:
        context = _context()
        candidate = MemoryCandidateService().create(
            MemoryCandidateCreate(
                title=context.title,
                body=context.content,
                scope=ContextScope.PROJECT,
                project="project-a",
                candidate_id="existing:context-1",
            )
        )
        decision = MemoryRelationDecision(
            candidate_id=candidate.candidate_id,
            existing_context_id="context-2",
            relation=MemoryRelationType.CONTRADICTS,
            confidence=0.96,
            reason="Claims conflict within overlapping validity intervals",
            evidence_refs=(),
            claim_matches=(),
            scores=MemoryRelationScores(
                semantic_similarity=0.9,
                claim_overlap=0.9,
                scope_compatibility=1.0,
                temporal_compatibility=1.0,
                source_independence=1.0,
                polarity_conflict=1.0,
                specificity_change=0.0,
                freshness=0.0,
            ),
            decision_source=MemoryDecisionSource.DETERMINISTIC,
            policy_version="test",
            created_at=now_utc(),
        )
        plan = MemoryReconciliationPlanService().build(
            candidate=candidate,
            decisions=(decision,),
            idempotency_key=f"existing-memory:context-1:{candidate.content_hash}",
        )
        service, compact, _, apply_service = _service(tmp_path, _preview(plan))

        preview = await service.execute(_request(MemoryCycleOperation.DRY_RUN))
        applied = await service.execute(
            _request(
                MemoryCycleOperation.APPLY,
                expected_plan_hash=preview.plan_hash,
            )
        )

        assert preview.status is MemoryCycleStatus.REVIEW_REQUIRED
        assert applied.status is MemoryCycleStatus.REVIEW_REQUIRED
        assert applied.compact_change is not None
        assert applied.compact_change.status is MemoryCompactStatus.DRAFT
        assert compact.mark_current_count == 0
        assert apply_service.calls == 0

    asyncio.run(scenario())


def test_memory_cycle_corrupt_checkpoint_requires_recovery_without_mutation(
    tmp_path: Path,
) -> None:
    """A malformed durable checkpoint cannot be treated as a fresh apply."""

    async def scenario() -> None:
        service, compact, _, _ = _service(tmp_path, _preview())
        preview = await service.execute(_request(MemoryCycleOperation.DRY_RUN))
        applied = await service.execute(
            _request(
                MemoryCycleOperation.APPLY,
                expected_plan_hash=preview.plan_hash,
            )
        )
        assert applied.status is MemoryCycleStatus.APPLIED
        checkpoint_path = (
            tmp_path
            / ".alexandria"
            / "report-bundle-runs"
            / f"{hashlib.sha256(b'memory-cycle:cycle-test').hexdigest()}.json"
        )
        checkpoint_path.write_text('{"foreign":true}', encoding="utf-8")

        with pytest.raises(ObsidianCheckpointRecoveryRequiredError):
            await service.execute(
                _request(
                    MemoryCycleOperation.APPLY,
                    expected_plan_hash=preview.plan_hash,
                )
            )

        assert compact.create_count == 1

    asyncio.run(scenario())
