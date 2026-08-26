"""Phase 9 bounded AUTO graph candidate expansion contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio

from app.memory.application.contexts.graph.context_graph_candidate_expansion_service import (
    ContextGraphCandidateExpansionService,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextRecallFilter,
    ScopeIdentity,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextGraphDirection,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
)
from app.memory.domain.repositories.contexts.graph.context_graph_candidate_hydrator import (
    ContextGraphHydratedCandidate,
    IContextGraphCandidateHydrator,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphCandidatePathHop,
    ObsidianGraphCandidateSelectionResult,
    ObsidianGraphProjection,
    ObsidianGraphProjectionNode,
    ObsidianGraphSelectedCandidate,
    ObsidianGraphTitleRelevance,
    ObsidianGraphTraversalRequest,
    ObsidianGraphTraversalResult,
    ObsidianGraphTraversalVisit,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphTraversalDirection,
)
from app.obsidian.domain.repositories.obsidian_graph_candidate_selection_compute_provider import (
    IObsidianGraphCandidateSelectionComputeProvider,
)

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def _projection() -> ObsidianGraphProjection:
    return ObsidianGraphProjection(
        nodes=(
            ObsidianGraphProjectionNode(
                note_id="graph-bridge",
                relative_path="Contexts/graph-bridge.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="Graph Bridge",
                status="active",
                project="heterarchy-alexandria",
            ),
            ObsidianGraphProjectionNode(
                note_id="graph-target",
                relative_path="Contexts/graph-target.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="graph-target",
                status="active",
                project="heterarchy-alexandria",
            ),
        ),
        edges=(),
    )


class _ProjectionSource:
    def __init__(self, projection: ObsidianGraphProjection) -> None:
        self.projection = projection
        self.calls = 0

    async def snapshot(self) -> ObsidianGraphProjection:
        self.calls += 1
        return self.projection


class _RecordingSelector(IObsidianGraphCandidateSelectionComputeProvider):
    def __init__(self) -> None:
        self.calls: list[
            tuple[
                tuple[ObsidianGraphTraversalRequest, ...],
                tuple[str, ...],
                str,
                int,
                int,
            ]
        ] = []

    @property
    def authority(self) -> str:
        return "rust:graph_compute:candidate_selection:v1"

    def select_candidates(
        self,
        projection: ObsidianGraphProjection,
        requests: tuple[ObsidianGraphTraversalRequest, ...],
        primary_note_ids: tuple[str, ...],
        query: str,
        max_candidates: int,
        min_shared_trigrams: int,
    ) -> ObsidianGraphCandidateSelectionResult:
        del projection
        self.calls.append(
            (
                requests,
                primary_note_ids,
                query,
                max_candidates,
                min_shared_trigrams,
            )
        )
        return ObsidianGraphCandidateSelectionResult(
            traversals=(
                ObsidianGraphTraversalResult(
                    request_id=requests[0].request_id,
                    start_note_id="primary-a",
                    start_found=True,
                    visits=(
                        ObsidianGraphTraversalVisit(note_id="primary-a", depth=0),
                        ObsidianGraphTraversalVisit(note_id="graph-bridge", depth=1),
                        ObsidianGraphTraversalVisit(note_id="graph-target", depth=2),
                    ),
                    truncated=False,
                ),
                ObsidianGraphTraversalResult(
                    request_id=requests[1].request_id,
                    start_note_id="primary-b",
                    start_found=True,
                    visits=(ObsidianGraphTraversalVisit(note_id="primary-b", depth=0),),
                    truncated=False,
                ),
            ),
            candidates=(
                ObsidianGraphSelectedCandidate(
                    note_id="graph-target",
                    min_depth=2,
                    seed_support=1,
                    shared_title_trigrams=8,
                    title_trigram_union=10,
                    path_hops=(
                        ObsidianGraphCandidatePathHop(
                            edge_id="edge-a-bridge",
                            source_note_id="primary-a",
                            target_note_id="graph-bridge",
                            relation="wikilink",
                            direction=ObsidianGraphTraversalDirection.OUTGOING,
                            depth=1,
                        ),
                        ObsidianGraphCandidatePathHop(
                            edge_id="edge-bridge-target",
                            source_note_id="graph-bridge",
                            target_note_id="graph-target",
                            relation="wikilink",
                            direction=ObsidianGraphTraversalDirection.OUTGOING,
                            depth=2,
                        ),
                    ),
                ),
            ),
            primary_title_relevance=(
                ObsidianGraphTitleRelevance(
                    note_id="primary-a",
                    shared_title_trigrams=2,
                    title_trigram_union=10,
                ),
                ObsidianGraphTitleRelevance(
                    note_id="primary-b",
                    shared_title_trigrams=5,
                    title_trigram_union=10,
                ),
            ),
        )


class _RecordingHydrator(IContextGraphCandidateHydrator):
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], ContextRecallFilter]] = []

    async def hydrate(
        self,
        note_ids: tuple[str, ...],
        recall_filter: ContextRecallFilter,
    ) -> tuple[ContextGraphHydratedCandidate, ...]:
        self.calls.append((note_ids, recall_filter))
        return (
            ContextGraphHydratedCandidate(
                note_id="graph-target",
                context=_context("graph-target"),
                chunk=_chunk("graph-target"),
            ),
        )


class _FailIfCalledSelector(_RecordingSelector):
    def select_candidates(
        self,
        projection: ObsidianGraphProjection,
        requests: tuple[ObsidianGraphTraversalRequest, ...],
        primary_note_ids: tuple[str, ...],
        query: str,
        max_candidates: int,
        min_shared_trigrams: int,
    ) -> ObsidianGraphCandidateSelectionResult:
        raise AssertionError("selector must not run for mixed-source primary recall")


def test_expansion_uses_measured_profile_and_reranks_bounded_union() -> None:
    projection_source = _ProjectionSource(_projection())
    selector = _RecordingSelector()
    hydrator = _RecordingHydrator()
    service = ContextGraphCandidateExpansionService(
        projection_source=projection_source,
        selector=selector,
        hydrator=hydrator,
    )
    recall_filter = _recall_filter()

    result = anyio.run(
        service.expand,
        "이 기억은 무엇과 관련되어 있고 어떤 graph relation이 있나?",
        [_match("primary-a", 0.9), _match("primary-b", 0.8)],
        recall_filter,
        3,
        2,
    )

    assert projection_source.calls == 1
    assert len(selector.calls) == 1
    requests, primary_ids, query, max_candidates, min_shared = selector.calls[0]
    assert primary_ids == ("primary-a", "primary-b")
    assert query.startswith("이 기억은")
    assert max_candidates == 3
    assert min_shared == 3
    assert len(requests) == 2
    assert all(request.direction.value == "both" for request in requests)
    assert all(request.relations == ("wikilink",) for request in requests)
    assert all(request.max_depth == 2 for request in requests)
    assert all(request.max_results == 50 for request in requests)
    assert hydrator.calls[0][0] == ("graph-target",)
    assert [match.context.id for match in result.matches] == [
        "graph-target",
        "primary-b",
        "primary-a",
    ]
    assert [match.graph_score for match in result.matches] == [0.8, 0.5, 0.2]
    graph_match = result.matches[0]
    assert graph_match.fts_score is None
    assert graph_match.vector_score is None
    assert len(graph_match.graph_evidence) == 2
    assert [item.direction for item in graph_match.graph_evidence] == [
        ContextGraphDirection.OUTGOING,
        ContextGraphDirection.OUTGOING,
    ]
    assert [item.distance for item in graph_match.graph_evidence] == [1, 2]
    assert graph_match.graph_evidence[0].source_context_id == "primary-a"
    assert graph_match.graph_evidence[0].target_context_id == "obsidian:graph-bridge"
    assert graph_match.graph_evidence[0].target_title == "Graph Bridge"
    assert graph_match.graph_evidence[1].source_context_id == "obsidian:graph-bridge"
    assert graph_match.graph_evidence[1].target_context_id == "graph-target"
    assert all(
        item.evidence_ref.startswith("graph:path:primary-a:graph-target:")
        for item in graph_match.graph_evidence
    )
    assert result.discovered_candidate_count == 2
    assert result.selected_candidate_count == 1
    assert result.hydrated_candidate_count == 1
    assert result.filtered_candidate_count == 0
    assert result.appended_candidate_count == 1


def test_expansion_preserves_mixed_source_primary_without_native_or_hydration_calls() -> (
    None
):
    projection_source = _ProjectionSource(_projection())
    selector = _FailIfCalledSelector()
    hydrator = _RecordingHydrator()
    service = ContextGraphCandidateExpansionService(
        projection_source=projection_source,
        selector=selector,
        hydrator=hydrator,
    )
    obsidian = _match("primary-a", 0.9)
    foreign = _match("foreign", 0.8, obsidian_note_id=None)

    result = anyio.run(
        service.expand,
        "graph relation",
        [obsidian, foreign],
        _recall_filter(),
        5,
        2,
    )

    assert [match.context.id for match in result.matches] == ["primary-a", "foreign"]
    assert result.selected_candidate_count == 0
    assert result.warnings == (
        "Graph multi-hop expansion skipped because primary recall contains non-Obsidian sources.",
    )
    assert projection_source.calls == 0
    assert hydrator.calls == []


def _recall_filter() -> ContextRecallFilter:
    return ContextRecallFilter(
        limit=5,
        kind=None,
        scope_identity=ScopeIdentity(
            include_scopes=(ContextScope.PROJECT, ContextScope.GLOBAL),
            project="heterarchy-alexandria",
            workspace_id=None,
            agent_id=None,
            user_id=None,
            session_id=None,
        ),
        lifecycle_statuses=None,
    )


def _context(note_id: str, obsidian_note_id: str | None = None) -> ContextRecord:
    metadata = ContextMetadataPayload(canonical_context_id=f"obsidian:{note_id}")
    if obsidian_note_id is not None or note_id != "foreign":
        metadata["obsidian_note_id"] = obsidian_note_id or note_id
    return ContextRecord(
        id=note_id,
        kind=ContextKind.HANDOFF,
        title=note_id.replace("-", " ").title(),
        summary="summary",
        content="content",
        content_format=ContextContentFormat.MARKDOWN,
        project="heterarchy-alexandria",
        scope=ContextScope.PROJECT,
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="test",
        source_type=ContextSourceType.IMPORTED,
        importance=ContextImportance.HIGH,
        tags=(),
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=(),
        restore_prompt=None,
        context_metadata=metadata,
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )


def _chunk(note_id: str) -> ContextChunkRecord:
    return ContextChunkRecord(
        id=f"chunk-{note_id}",
        context_id=note_id,
        chunk_index=0,
        heading=None,
        content=f"{note_id} content",
        token_count=3,
        content_hash=f"hash-{note_id}",
        chunk_metadata=ContextMetadataPayload(),
        created_at=NOW,
    )


def _match(
    note_id: str,
    score: float,
    *,
    obsidian_note_id: str | None = "auto",
) -> ContextSearchMatch:
    resolved_note_id = note_id if obsidian_note_id == "auto" else obsidian_note_id
    return ContextSearchMatch(
        context=_context(note_id, resolved_note_id),
        chunk=_chunk(note_id),
        score=score,
        fts_score=score,
        vector_score=None,
        why_retrieved="Primary retrieval evidence.",
    )
