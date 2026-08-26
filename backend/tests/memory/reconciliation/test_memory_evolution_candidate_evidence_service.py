"""Pure application tests for Phase 7 Rust candidate-evidence orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import anyio

from app.memory.application.reconciliation.candidates.memory_evolution_candidate_evidence_service import (
    MemoryEvolutionCandidateEvidenceService,
)
from app.memory.application.retrieval.embeddings.fake_embedding_provider import (
    FakeEmbeddingProvider,
)
from app.memory.domain.contracts.memory_reconciliation_candidate_compute_contracts import (
    ReconciliationCandidateComputeItem,
    ReconciliationCandidateComputeMetrics,
    ReconciliationCandidateComputePolicy,
    ReconciliationCandidateComputeResult,
    ReconciliationCandidateEvidence,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemoryEvolutionCandidateEvidence,
    MemoryRecallCandidate,
    MemoryReconciliationPlan,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryReconciliationStatus,
    MemoryRelationType,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_candidate_compute_provider import (
    IMemoryReconciliationCandidateComputeProvider,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_payload_mapper import (
    plan_from_payload,
    plan_payload,
)
from app.memory.interface.schemas.reconciliation.memory_reconciliation_plan_detail_schema import (
    MemoryReconciliationPlanResponse,
)

NOW = datetime(2026, 8, 25, tzinfo=UTC)


class _RecordingEmbeddingProvider(FakeEmbeddingProvider):
    """Record one canonical bulk embedding call while reusing deterministic vectors."""

    def __init__(self) -> None:
        super().__init__(dimensions=8)
        self.calls: list[tuple[str, ...]] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Record ordered document texts and return deterministic embeddings.

        Args:
            texts: Ordered canonical document texts.

        Returns:
            One deterministic vector per input document.
        """
        self.calls.append(tuple(texts))
        return super().embed_documents(texts)


class _FakeCandidateComputeProvider(IMemoryReconciliationCandidateComputeProvider):
    """Capture candidate-compute inputs while returning deterministic typed evidence."""

    def __init__(self) -> None:
        self.items: tuple[ReconciliationCandidateComputeItem, ...] = ()
        self.policy: ReconciliationCandidateComputePolicy | None = None

    @property
    def authority(self) -> str:
        """Return the fake deterministic compute authority."""
        return "test:reconciliation_candidates:v1"

    def discover(
        self,
        items: tuple[ReconciliationCandidateComputeItem, ...],
        policy: ReconciliationCandidateComputePolicy,
    ) -> ReconciliationCandidateComputeResult:
        """Return source evidence plus one unrelated existing-to-existing pair."""
        self.items = items
        self.policy = policy
        source_id = items[0].item_id
        existing_ids = sorted(item.item_id for item in items[1:])
        pairs = (
            ReconciliationCandidateEvidence(
                left_id=source_id,
                right_id=existing_ids[0],
                exact_content_hash=True,
                vector_similarity=None,
                temporal_overlap=True,
                graph_similarity=0.0,
                lineage="NONE",
                candidate_score=1.0,
                reasons=("exact_content_hash",),
            ),
            ReconciliationCandidateEvidence(
                left_id=existing_ids[0],
                right_id=existing_ids[1],
                exact_content_hash=False,
                vector_similarity=None,
                temporal_overlap=True,
                graph_similarity=0.0,
                lineage="NONE",
                candidate_score=0.1,
                reasons=("temporal_overlap",),
            ),
        )
        return ReconciliationCandidateComputeResult(
            exact_duplicate_groups=(),
            candidate_pairs=pairs,
            clusters=(),
            metrics=ReconciliationCandidateComputeMetrics(
                input_items=len(items),
                comparison_pairs=2,
                qualifying_pairs=2,
                retained_pairs=2,
                exact_duplicate_groups=0,
            ),
        )


def _candidate() -> MemoryCandidate:
    """Return one normalized source proposal without invoking hashing adapters."""
    return MemoryCandidate(
        candidate_id="candidate-1",
        title="New storage decision",
        body="heterarchy-alexandria uses PostgreSQL.",
        canonical_claims=(),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        tags=(),
        source_refs=(),
        recorded_at=NOW,
        observed_at=None,
        valid_from=NOW,
        valid_to=None,
        requested_lifecycle="active",
        content_hash="a" * 64,
        graph_neighbors=("graph-shared", "graph-candidate"),
        lineage_ancestors=("ctx-ancestor",),
    )


def _recalled(
    context_id: str,
    content_hash: str,
    graph_neighbors: tuple[str, ...] = (),
    lineage_ancestors: tuple[str, ...] = (),
) -> MemoryRecallCandidate:
    """Return one stored Context candidate for deterministic evidence tests."""
    return MemoryRecallCandidate(
        context_id=context_id,
        title=context_id,
        body=context_id,
        canonical_claims=(),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        source_identity=None,
        content_hash=content_hash,
        recorded_at=NOW,
        observed_at=None,
        valid_from=NOW,
        valid_to=None,
        graph_neighbors=graph_neighbors,
        lineage_ancestors=lineage_ancestors,
    )


def test_evidence_service_builds_bounded_source_pairs_without_semantic_pruning() -> (
    None
):
    """Rust evidence should cover all recalled Contexts but retain only source-related pairs."""
    provider = _FakeCandidateComputeProvider()
    service = MemoryEvolutionCandidateEvidenceService(provider)
    recalled = (
        _recalled("ctx-z", "z" * 64),
        _recalled(
            "ctx-a",
            "a" * 64,
            graph_neighbors=("graph-shared", "graph-a"),
            lineage_ancestors=("ctx-older",),
        ),
    )

    evidence = anyio.run(service.discover, _candidate(), recalled)

    assert evidence.compute_authority == "test:reconciliation_candidates:v1"
    assert evidence.compared_context_ids == ("ctx-a", "ctx-z")
    assert [(pair.left_id, pair.right_id) for pair in evidence.candidate_pairs] == [
        ("candidate-1", "ctx-a")
    ]
    assert provider.policy is not None
    assert provider.policy.max_block_size == 2
    assert provider.policy.max_candidates_per_item == 2
    assert len(provider.items) == 3
    assert provider.items[0].blocking_keys == ("source-pair:0", "source-pair:1")
    assert provider.items[0].graph_neighbors == ("graph-shared", "graph-candidate")
    assert provider.items[0].lineage_ancestors == ("ctx-ancestor",)
    assert provider.items[1].item_id == "ctx-a"
    assert provider.items[1].blocking_keys == ("source-pair:0",)
    assert provider.items[1].graph_neighbors == ("graph-shared", "graph-a")
    assert provider.items[1].lineage_ancestors == ("ctx-older",)
    assert provider.items[2].item_id == "ctx-z"
    assert provider.items[2].blocking_keys == ("source-pair:1",)


def test_evidence_service_empty_recall_still_emits_auditable_metrics() -> None:
    """No recalled Context must remain an explicit zero-work Rust evidence result."""
    provider = _FakeCandidateComputeProvider()
    service = MemoryEvolutionCandidateEvidenceService(provider)

    # The fake assumes two existing items when constructing pairs, so return a zero result here.
    def empty_discover(
        items: tuple[ReconciliationCandidateComputeItem, ...],
        policy: ReconciliationCandidateComputePolicy,
    ) -> ReconciliationCandidateComputeResult:
        provider.items = items
        provider.policy = policy
        return ReconciliationCandidateComputeResult(
            exact_duplicate_groups=(),
            candidate_pairs=(),
            clusters=(),
            metrics=ReconciliationCandidateComputeMetrics(
                input_items=1,
                comparison_pairs=0,
                qualifying_pairs=0,
                retained_pairs=0,
                exact_duplicate_groups=0,
            ),
        )

    provider.discover = empty_discover  # type: ignore[method-assign]
    evidence = anyio.run(service.discover, _candidate(), ())

    assert evidence.compared_context_ids == ()
    assert evidence.candidate_pairs == ()
    assert evidence.metrics.input_items == 1
    assert provider.policy is not None
    assert provider.policy.max_candidates_per_item == 1


def test_evidence_service_skips_embedding_when_no_pair_can_exist() -> None:
    """No-match preview should not pay embedding cost when Rust has no pair to compare."""
    compute_provider = _FakeCandidateComputeProvider()
    embedding_provider = _RecordingEmbeddingProvider()
    service = MemoryEvolutionCandidateEvidenceService(
        compute_provider,
        embedding_provider=embedding_provider,
    )

    def empty_discover(items, policy):
        compute_provider.items = items
        compute_provider.policy = policy
        return ReconciliationCandidateComputeResult(
            exact_duplicate_groups=(),
            candidate_pairs=(),
            clusters=(),
            metrics=ReconciliationCandidateComputeMetrics(
                input_items=1,
                comparison_pairs=0,
                qualifying_pairs=0,
                retained_pairs=0,
                exact_duplicate_groups=0,
            ),
        )

    compute_provider.discover = empty_discover  # type: ignore[method-assign]
    evidence = anyio.run(service.discover, _candidate(), ())

    assert embedding_provider.calls == []
    assert compute_provider.items[0].embedding is None
    assert evidence.metrics.comparison_pairs == 0


def test_evidence_service_bulk_embeds_transient_vectors_without_persisting_them() -> (
    None
):
    """Candidate and recalled bodies should be embedded once and only fed to Rust inputs."""
    compute_provider = _FakeCandidateComputeProvider()
    embedding_provider = _RecordingEmbeddingProvider()
    service = MemoryEvolutionCandidateEvidenceService(
        compute_provider,
        embedding_provider=embedding_provider,
    )
    recalled = (
        _recalled("ctx-z", "z" * 64),
        _recalled("ctx-a", "b" * 64),
    )

    evidence = anyio.run(service.discover, _candidate(), recalled)

    assert len(embedding_provider.calls) == 1
    embedded_texts = embedding_provider.calls[0]
    assert len(embedded_texts) == 3
    assert embedded_texts[0].startswith("Title: New storage decision\n")
    assert embedded_texts[1].startswith("Title: ctx-a\n")
    assert embedded_texts[2].startswith("Title: ctx-z\n")
    assert all(item.embedding is not None for item in compute_provider.items)
    assert all(
        len(item.embedding) == embedding_provider.dimensions
        for item in compute_provider.items
        if item.embedding is not None
    )
    assert evidence.compute_authority == "test:reconciliation_candidates:v1"


def test_candidate_evidence_round_trips_through_plan_persistence_and_bounded_response() -> (
    None
):
    """Persisted Rust evidence should survive JSON round-trip without raw vectors or bodies."""
    pair = ReconciliationCandidateEvidence(
        left_id="candidate-1",
        right_id="ctx-a",
        exact_content_hash=True,
        vector_similarity=0.95,
        temporal_overlap=True,
        graph_similarity=0.5,
        lineage="NONE",
        candidate_score=1.0,
        reasons=("exact_content_hash", "vector_similarity"),
    )
    evidence = MemoryEvolutionCandidateEvidence(
        compute_authority="rust:reconciliation_candidates:v1",
        candidate_item_id="candidate-1",
        compared_context_ids=("ctx-a",),
        candidate_pairs=(pair,),
        metrics=ReconciliationCandidateComputeMetrics(
            input_items=2,
            comparison_pairs=1,
            qualifying_pairs=1,
            retained_pairs=1,
            exact_duplicate_groups=1,
        ),
    )
    plan = MemoryReconciliationPlan(
        plan_id="plan-1",
        candidate=_candidate(),
        decisions=(),
        primary_decision=MemoryRelationType.UNRELATED,
        actions=(),
        warnings=(),
        conflicting_context_ids=(),
        requires_review=False,
        idempotency_key="idem-1",
        status=MemoryReconciliationStatus.PLANNED,
        created_at=NOW,
        candidate_evidence=evidence,
    )

    restored = plan_from_payload(plan_payload(plan))
    response = MemoryReconciliationPlanResponse.from_entity(restored)
    response_evidence = response.model_dump(mode="json")["candidate_evidence"]

    assert restored == plan
    assert response_evidence is not None
    assert response_evidence["compute_authority"] == "rust:reconciliation_candidates:v1"
    assert response_evidence["candidate_pairs"][0]["right_id"] == "ctx-a"
    assert response_evidence["metrics"]["comparison_pairs"] == 1
    assert "embedding" not in response_evidence
    assert "body" not in response_evidence
