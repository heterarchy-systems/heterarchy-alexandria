"""Build bounded Rust candidate evidence for proposal-first memory evolution."""

from __future__ import annotations

from asyncer import asyncify

from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProvider,
)
from app.memory.application.retrieval.embeddings.embedding_document import (
    build_embedding_document_text,
)
from app.memory.domain.contracts.memory_reconciliation_candidate_compute_contracts import (
    ReconciliationCandidateComputeItem,
    ReconciliationCandidateComputePolicy,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemoryEvolutionCandidateEvidence,
    MemoryRecallCandidate,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_candidate_compute_provider import (
    IMemoryReconciliationCandidateComputeProvider,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError


class MemoryEvolutionCandidateEvidenceService:
    """Produce deterministic candidate evidence without assigning semantic relations."""

    def __init__(
        self,
        provider: IMemoryReconciliationCandidateComputeProvider,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        """Create the proposal evidence service.

        Args:
            provider: Rust-backed deterministic candidate-compute authority.
            embedding_provider: Optional canonical local embedding provider.
        """
        self._provider = provider
        self._embedding_provider = embedding_provider

    async def discover(
        self,
        candidate: MemoryCandidate,
        recalled: tuple[MemoryRecallCandidate, ...],
    ) -> MemoryEvolutionCandidateEvidence:
        """Compute source-to-recalled evidence while preserving Python policy authority.

        The generated blocking keys compare the source candidate with every recalled
        Context in O(N) candidate pairs. Existing-to-existing comparisons are not
        requested by this application lane, and absence of Rust evidence never means
        that Python policy should classify a recalled Context as unrelated.

        Args:
            candidate: New or updated durable-memory proposal.
            recalled: Python-selected historical Context candidates.

        Returns:
            Proposal evidence and bounded-work metrics for audit/persistence.
        """
        ordered = tuple(sorted(recalled, key=lambda value: value.context_id))
        embeddings = await _transient_embeddings(
            self._embedding_provider, candidate, ordered
        )
        pair_keys = tuple(f"source-pair:{index}" for index in range(len(ordered)))
        items = [
            ReconciliationCandidateComputeItem(
                item_id=candidate.candidate_id,
                content_hash=candidate.content_hash,
                embedding=embeddings[0],
                valid_from=candidate.valid_from,
                valid_to=candidate.valid_to,
                blocking_keys=pair_keys,
                graph_neighbors=candidate.graph_neighbors,
                lineage_ancestors=candidate.lineage_ancestors,
            )
        ]
        items.extend(
            ReconciliationCandidateComputeItem(
                item_id=existing.context_id,
                content_hash=existing.content_hash,
                embedding=embeddings[index + 1],
                valid_from=existing.valid_from,
                valid_to=existing.valid_to,
                blocking_keys=(pair_keys[index],),
                graph_neighbors=existing.graph_neighbors,
                lineage_ancestors=existing.lineage_ancestors,
            )
            for index, existing in enumerate(ordered)
        )
        result = self._provider.discover(
            tuple(items),
            ReconciliationCandidateComputePolicy(
                max_block_size=2,
                max_candidates_per_item=max(1, len(ordered)),
            ),
        )
        candidate_pairs = tuple(
            pair
            for pair in result.candidate_pairs
            if candidate.candidate_id in {pair.left_id, pair.right_id}
        )
        return MemoryEvolutionCandidateEvidence(
            compute_authority=self._provider.authority,
            candidate_item_id=candidate.candidate_id,
            compared_context_ids=tuple(value.context_id for value in ordered),
            candidate_pairs=candidate_pairs,
            metrics=result.metrics,
        )


async def _transient_embeddings(
    provider: EmbeddingProvider | None,
    candidate: MemoryCandidate,
    recalled: tuple[MemoryRecallCandidate, ...],
) -> tuple[tuple[float, ...] | None, ...]:
    """Embed proposal bodies once for transient Rust evidence computation.

    Args:
        provider: Optional canonical embedding provider.
        candidate: Source memory proposal.
        recalled: Ordered historical Context candidates.

    Returns:
        One optional immutable vector per source/recalled item.

    Raises:
        MemoryContextValidationError: If provider cardinality or dimensions drift.
    """
    item_count = len(recalled) + 1
    if not recalled or provider is None:
        return tuple(None for _ in range(item_count))
    texts = [
        build_embedding_document_text(candidate.body, candidate.title, None),
        *(
            build_embedding_document_text(item.body, item.title, None)
            for item in recalled
        ),
    ]
    vectors = await asyncify(provider.embed_documents, abandon_on_cancel=True)(texts)
    if len(vectors) != item_count:
        raise MemoryContextValidationError(
            "memory evolution embedding provider returned an unexpected item count"
        )
    if any(len(vector) != provider.dimensions for vector in vectors):
        raise MemoryContextValidationError(
            "memory evolution embedding provider returned an unexpected dimension"
        )
    return tuple(tuple(vector) for vector in vectors)
