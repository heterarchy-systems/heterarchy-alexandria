"""AUTO-only graph candidate expansion over the active Obsidian projection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cmp_to_key
from typing import Protocol

from app.memory.domain.contracts.context_recall_contracts import ContextRecallFilter
from app.memory.domain.entities.context_read_models import (
    ContextGraphEvidence,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import (
    ContextGraphDirection,
    ContextGraphSignalType,
)
from app.memory.domain.repositories.contexts.graph.context_graph_candidate_expansion_provider import (
    ContextGraphCandidateExpansionResult,
    IContextGraphCandidateExpansionProvider,
)
from app.memory.domain.repositories.contexts.graph.context_graph_candidate_hydrator import (
    ContextGraphHydratedCandidate,
    IContextGraphCandidateHydrator,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphCandidateSelectionResult,
    ObsidianGraphProjection,
    ObsidianGraphSelectedCandidate,
    ObsidianGraphTraversalRequest,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphTraversalDirection,
)
from app.obsidian.domain.repositories.obsidian_graph_candidate_selection_compute_provider import (
    IObsidianGraphCandidateSelectionComputeProvider,
)

_GRAPH_SEED_LIMIT = 2
_GRAPH_TRAVERSAL_MAX_RESULTS = 50
_GRAPH_SELECTED_LIMIT = 3
_GRAPH_MIN_SHARED_TRIGRAMS = 3
_GRAPH_RELATIONS = ("wikilink",)


# protocol-contract: structural-seam
class GraphProjectionSnapshotSource(Protocol):
    """Narrow active-projection snapshot dependency used by graph expansion."""

    async def snapshot(self) -> ObsidianGraphProjection:
        """Return the current active projection snapshot.

        Returns:
            Immutable active graph projection.
        """


@dataclass(frozen=True, slots=True)
class _RankedGraphMatch:
    match: ContextSearchMatch
    shared: int
    union: int
    original_order: int


class ContextGraphCandidateExpansionService(IContextGraphCandidateExpansionProvider):
    """Apply evidence-backed multi-hop expansion only for AUTO graph-intent recall."""

    def __init__(
        self,
        projection_source: GraphProjectionSnapshotSource,
        selector: IObsidianGraphCandidateSelectionComputeProvider,
        hydrator: IContextGraphCandidateHydrator,
    ) -> None:
        """Initialize graph expansion dependencies.

        Args:
            projection_source: Active Neo4j projection snapshot source.
            selector: Authoritative Rust graph candidate selector.
            hydrator: PostgreSQL-backed canonical Context candidate hydrator.
        """
        self._projection_source = projection_source
        self._selector = selector
        self._hydrator = hydrator

    async def expand(
        self,
        query: str,
        matches: list[ContextSearchMatch],
        recall_filter: ContextRecallFilter,
        limit: int,
        graph_depth: int,
    ) -> ContextGraphCandidateExpansionResult:
        """Expand one graph-intent result set with the measured bounded profile.

        Args:
            query: Original retrieval query.
            matches: Primary retrieval matches in existing rank order.
            recall_filter: Existing scope/lifecycle visibility boundary.
            limit: Public final result bound.
            graph_depth: Planner-authoritative traversal depth for this request.

        Returns:
            Bounded graph-aware final matches and non-fatal warnings.
        """
        if not matches or limit < 1:
            return ContextGraphCandidateExpansionResult(matches=tuple(matches[:limit]))
        primary_note_ids = tuple(_obsidian_note_id(match) for match in matches)
        if any(note_id is None for note_id in primary_note_ids):
            return ContextGraphCandidateExpansionResult(
                matches=tuple(matches[:limit]),
                warnings=(
                    "Graph multi-hop expansion skipped because primary recall contains "
                    "non-Obsidian sources.",
                ),
            )
        note_ids = tuple(note_id for note_id in primary_note_ids if note_id is not None)
        seeds = tuple(dict.fromkeys(note_ids))[:_GRAPH_SEED_LIMIT]
        if not seeds:
            return ContextGraphCandidateExpansionResult(matches=tuple(matches[:limit]))
        projection = await self._projection_source.snapshot()
        requests = tuple(
            ObsidianGraphTraversalRequest(
                request_id=f"auto-graph:{index}:{seed}",
                start_note_id=seed,
                direction=ObsidianGraphTraversalDirection.BOTH,
                relations=_GRAPH_RELATIONS,
                max_depth=graph_depth,
                max_results=_GRAPH_TRAVERSAL_MAX_RESULTS,
            )
            for index, seed in enumerate(seeds)
        )
        selection = self._selector.select_candidates(
            projection,
            requests,
            primary_note_ids=note_ids,
            query=query,
            max_candidates=_GRAPH_SELECTED_LIMIT,
            min_shared_trigrams=_GRAPH_MIN_SHARED_TRIGRAMS,
        )
        discovered_candidate_count = _discovered_candidate_count(selection, note_ids)
        selected_ids = tuple(
            candidate.note_id
            for candidate in selection.candidates
            if candidate.note_id not in set(note_ids)
        )
        hydrated = await self._hydrator.hydrate(selected_ids, recall_filter)
        graph_matches = _graph_candidate_matches(
            selection, hydrated, matches, projection
        )
        reranked = _rerank_union(matches, graph_matches, selection, limit)
        graph_context_ids = {match.context.id for match in graph_matches}
        return ContextGraphCandidateExpansionResult(
            matches=tuple(reranked),
            discovered_candidate_count=discovered_candidate_count,
            selected_candidate_count=len(selected_ids),
            hydrated_candidate_count=len(hydrated),
            filtered_candidate_count=max(0, len(selected_ids) - len(graph_matches)),
            appended_candidate_count=sum(
                match.context.id in graph_context_ids for match in reranked
            ),
        )


def _discovered_candidate_count(
    selection: ObsidianGraphCandidateSelectionResult,
    primary_note_ids: tuple[str, ...],
) -> int:
    """Count distinct non-primary nodes reached by bounded graph traversal.

    Args:
        selection: Rust traversal and candidate-selection evidence.
        primary_note_ids: Primary note identities excluded from discovery counts.

    Returns:
        Number of distinct traversal-discovered non-primary note identities.
    """
    primary_ids = set(primary_note_ids)
    return len(
        {
            visit.note_id
            for traversal in selection.traversals
            for visit in traversal.visits
            if visit.note_id not in primary_ids
        }
    )


def _obsidian_note_id(match: ContextSearchMatch) -> str | None:
    """Return the canonical Obsidian note identity for one primary match.

    Args:
        match: Primary Context search match.

    Returns:
        Canonical Obsidian note id when the match belongs to that source.
    """
    value = match.context.context_metadata.get("obsidian_note_id")
    return value if isinstance(value, str) and value.strip() else None


def _graph_candidate_matches(
    selection: ObsidianGraphCandidateSelectionResult,
    hydrated: tuple[ContextGraphHydratedCandidate, ...],
    primary_matches: list[ContextSearchMatch],
    projection: ObsidianGraphProjection,
) -> list[ContextSearchMatch]:
    """Map hydrated graph candidates to Context matches with graph provenance.

    Args:
        selection: Rust graph traversal and candidate-selection evidence.
        hydrated: Canonical Context/chunk pairs for selected note ids.
        primary_matches: Existing primary matches used as traversal seeds.
        projection: Active graph projection supplied to Rust selection.

    Returns:
        Graph-only Context matches carrying bounded multi-hop evidence.
    """
    by_note_id = {item.note_id: item for item in hydrated}
    primary_context_ids = {
        note_id: match.context.id
        for match in primary_matches
        if (note_id := _obsidian_note_id(match)) is not None
    }
    projection_titles = {node.note_id: node.title for node in projection.nodes}
    results: list[ContextSearchMatch] = []
    for candidate in selection.candidates:
        item = by_note_id.get(candidate.note_id)
        if item is None:
            continue
        graph_score = _ratio(
            candidate.shared_title_trigrams, candidate.title_trigram_union
        )
        evidence = _candidate_path_evidence(
            candidate,
            item,
            primary_context_ids,
            projection_titles,
        )
        results.append(
            ContextSearchMatch(
                context=item.context,
                chunk=item.chunk,
                score=graph_score,
                fts_score=None,
                vector_score=None,
                graph_score=graph_score,
                why_retrieved=(
                    "Selected by bounded Rust multi-hop graph traversal and query/title relevance."
                ),
                graph_evidence=evidence,
            )
        )
    return results


def _candidate_path_evidence(
    candidate: ObsidianGraphSelectedCandidate,
    hydrated: ContextGraphHydratedCandidate,
    primary_context_ids: dict[str, str],
    projection_titles: dict[str, str],
) -> tuple[ContextGraphEvidence, ...]:
    """Map Rust-owned shortest-path hops into bounded Context graph evidence.

    Args:
        candidate: Rust-selected candidate carrying authoritative shortest-path hops.
        hydrated: Canonical hydrated final candidate.
        primary_context_ids: Seed note ids mapped to recalled Context identities.
        projection_titles: Active projection title lookup for intermediate hop targets.

    Returns:
        One immutable evidence entry per Rust-owned shortest-path hop.

    Raises:
        ValueError: If projected titles or final candidate path identity disagree.
    """
    if not candidate.path_hops:
        raise ValueError("GRAPH_CANDIDATE_PATH_MISSING")
    if candidate.path_hops[-1].target_note_id != candidate.note_id:
        raise ValueError("GRAPH_CANDIDATE_PATH_TARGET_MISMATCH")
    seed_note_id = candidate.path_hops[0].source_note_id
    evidence: list[ContextGraphEvidence] = []
    for hop in candidate.path_hops:
        target_title = projection_titles.get(hop.target_note_id)
        if target_title is None:
            raise ValueError("GRAPH_CANDIDATE_PATH_TITLE_MISSING")
        target_context_id = (
            hydrated.context.id
            if hop.target_note_id == candidate.note_id
            else f"obsidian:{hop.target_note_id}"
        )
        evidence.append(
            ContextGraphEvidence(
                signal=ContextGraphSignalType.GRAPH_PROXIMITY,
                relation=hop.relation,
                direction=ContextGraphDirection(hop.direction.value),
                source_context_id=primary_context_ids.get(
                    hop.source_note_id, f"obsidian:{hop.source_note_id}"
                ),
                target_context_id=target_context_id,
                target_title=(
                    hydrated.context.title
                    if hop.target_note_id == candidate.note_id
                    else target_title
                ),
                distance=hop.depth,
                evidence_ref=(
                    f"graph:path:{seed_note_id}:{candidate.note_id}:"
                    f"{hop.edge_id}:d{hop.depth}"
                ),
            )
        )
    return tuple(evidence)


def _rerank_union(
    primary_matches: list[ContextSearchMatch],
    graph_matches: list[ContextSearchMatch],
    selection: ObsidianGraphCandidateSelectionResult,
    limit: int,
) -> list[ContextSearchMatch]:
    """Rerank the bounded primary-plus-graph union using Rust title evidence.

    Args:
        primary_matches: Existing primary retrieval results.
        graph_matches: Hydrated graph-discovered matches.
        selection: Rust title relevance for both primary and graph candidates.
        limit: Public final result bound.

    Returns:
        Graph-aware final matches ordered by deterministic title relevance.
    """
    primary_relevance = {
        item.note_id: item for item in selection.primary_title_relevance
    }
    candidate_relevance = {item.note_id: item for item in selection.candidates}
    union = list(primary_matches)
    seen_context_ids = {match.context.id for match in union}
    union.extend(
        match for match in graph_matches if match.context.id not in seen_context_ids
    )
    ranked: list[_RankedGraphMatch] = []
    for order, match in enumerate(union):
        note_id = _obsidian_note_id(match)
        if note_id is None:
            continue
        evidence = primary_relevance.get(note_id) or candidate_relevance.get(note_id)
        if evidence is None:
            continue
        score = _ratio(evidence.shared_title_trigrams, evidence.title_trigram_union)
        ranked.append(
            _RankedGraphMatch(
                match=replace(
                    match,
                    score=score,
                    graph_score=score,
                    why_retrieved=(
                        f"{match.why_retrieved} AUTO graph intent reranked this Context "
                        "using Rust query/title relevance."
                    ),
                ),
                shared=evidence.shared_title_trigrams,
                union=evidence.title_trigram_union,
                original_order=order,
            )
        )
    ranked.sort(key=cmp_to_key(_compare_ranked_matches))
    return [item.match for item in ranked[:limit]]


def _compare_ranked_matches(left: _RankedGraphMatch, right: _RankedGraphMatch) -> int:
    """Compare graph-aware matches without floating-point ordering drift.

    Args:
        left: Left ranked graph match.
        right: Right ranked graph match.

    Returns:
        Negative, zero, or positive comparator result for deterministic sorting.
    """
    left_cross = left.shared * right.union
    right_cross = right.shared * left.union
    if left_cross != right_cross:
        return -1 if left_cross > right_cross else 1
    if left.original_order != right.original_order:
        return -1 if left.original_order < right.original_order else 1
    if left.match.context.id < right.match.context.id:
        return -1
    if left.match.context.id > right.match.context.id:
        return 1
    return 0


def _ratio(shared: int, union: int) -> float:
    """Convert validated integer relevance evidence to a public graph score.

    Args:
        shared: Shared title/query trigram count.
        union: Title/query trigram union count.

    Returns:
        Bounded graph relevance ratio.

    Raises:
        ValueError: If the integer relevance evidence is invalid.
    """
    if union <= 0 or shared < 0 or shared > union:
        raise ValueError("GRAPH_TITLE_RELEVANCE_INVALID")
    return shared / union
