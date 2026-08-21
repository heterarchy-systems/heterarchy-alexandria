"""Graph evidence enrichment through the optional Neo4j projection provider."""

from __future__ import annotations

from dataclasses import replace

from app.memory.application.retrieval.context_retrieval_metadata import (
    canonical_context_id,
)
from app.memory.domain.entities.context_read_models import (
    ContextGraphEvidence,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import (
    ContextGraphDirection,
    ContextGraphSignalType,
)
from app.memory.domain.repositories.contexts.context_graph_signal_provider import (
    ContextGraphEnrichmentResult,
    IContextGraphSignalProvider,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphContextEvidence,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)

_MAX_GRAPH_EVIDENCE_PER_MATCH = 5


class ObsidianGraphContextSignalService(IContextGraphSignalProvider):
    """Attach explainable projection relationships without reranking matches."""

    def __init__(
        self,
        repository: IObsidianGraphProjectionRepository | None,
    ) -> None:
        """Initialize the optional projection reader.

        Args:
            repository: Enabled projection repository, or None while disabled.
        """
        self._repository = repository

    async def enrich(
        self,
        matches: list[ContextSearchMatch],
    ) -> ContextGraphEnrichmentResult:
        """Attach one-hop graph proximity and curation evidence.

        Args:
            matches: Primary FTS/vector results in final rank order.

        Returns:
            Matches with graph explanations and unchanged scores/order.
        """
        if self._repository is None or not matches:
            return ContextGraphEnrichmentResult(matches=tuple(matches))

        allowed_context_ids = tuple(
            canonical_context_id(match.context) for match in matches
        )
        graph_evidence = await self._repository.context_evidence(
            note_ids=allowed_context_ids
        )
        edges_by_note_id: dict[str, list[ObsidianGraphContextEvidence]] = {}
        for edge in graph_evidence:
            edges_by_note_id.setdefault(edge.source_note_id, []).append(edge)
            edges_by_note_id.setdefault(edge.target_note_id, []).append(edge)

        enriched = [
            _enrich_match(
                match,
                edges=edges_by_note_id.get(canonical_context_id(match.context), []),
            )
            for match in matches
        ]
        return ContextGraphEnrichmentResult(matches=tuple(enriched))


def _enrich_match(
    match: ContextSearchMatch,
    edges: list[ObsidianGraphContextEvidence],
) -> ContextSearchMatch:
    context_id = canonical_context_id(match.context)
    evidence_items: list[ContextGraphEvidence] = []
    for edge in edges:
        item = _graph_evidence(
            context_id=context_id,
            edge=edge,
        )
        if item is not None:
            evidence_items.append(item)
    evidence = tuple(evidence_items[:_MAX_GRAPH_EVIDENCE_PER_MATCH])
    if not evidence:
        return match
    explanation = "; ".join(
        f"graph {item.signal.value} via {item.relation} to {item.target_title} "
        f"(direction={item.direction.value})"
        for item in evidence
    )
    return replace(
        match,
        why_retrieved=f"{match.why_retrieved} {explanation}.",
        graph_evidence=evidence,
    )


def _graph_evidence(
    context_id: str,
    edge: ObsidianGraphContextEvidence,
) -> ContextGraphEvidence | None:
    direction = _direction(context_id=context_id, edge=edge)
    if direction is None:
        return None
    evidence_ref = (
        f"graph://{edge.source_note_id}/{edge.relation.value}/{edge.target_note_id}"
    )
    return ContextGraphEvidence(
        signal=ContextGraphSignalType(edge.signal.value),
        relation=edge.relation.value,
        direction=direction,
        source_context_id=edge.source_note_id,
        target_context_id=edge.target_note_id,
        target_title=edge.target_title,
        distance=1,
        evidence_ref=evidence_ref,
    )


def _direction(
    context_id: str,
    edge: ObsidianGraphContextEvidence,
) -> ContextGraphDirection | None:
    if edge.source_note_id == context_id:
        return ContextGraphDirection.OUTGOING
    if edge.target_note_id == context_id:
        return ContextGraphDirection.INCOMING
    return None
