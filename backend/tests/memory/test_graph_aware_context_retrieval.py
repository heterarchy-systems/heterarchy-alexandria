"""Graph-aware Context recall contracts over the optional projection read model."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import anyio
import pytest
from app.memory.application.context_embedding_service import ContextEmbeddingService
from app.memory.application.context_search_service import ContextSearchService
from app.memory.domain.contracts.context_contracts import ContextChunkEmbeddingUpdate
from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
    ContextVectorRecall,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextEmbeddingSourceStatus,
    ContextPack,
    ContextRecord,
    ContextSearchMatch,
    RagDependencyHealth,
)
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextGraphDirection,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    RagHealthState,
    RagStrategy,
)
from app.memory.domain.repositories.context_graph_signal_provider import (
    ContextGraphEnrichmentResult,
    IContextGraphSignalProvider,
)
from app.memory.domain.repositories.context_search_source import IContextSearchSource
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.memory.interface.schemas.context.context_mapping import match_payload
from app.obsidian.application.graph.obsidian_graph_context_signal_service import (
    ObsidianGraphContextSignalService,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionNode,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.shared.types.extra_types import JSONObject
from tests.obsidian.graph.fakes.fake_obsidian_graph_projection_repository import (
    FakeObsidianGraphProjectionRepository,
)

NOW = datetime(2026, 8, 3, tzinfo=UTC)


class _HybridSearchSource(IContextSearchSource):
    def __init__(self, fts_matches: list[ContextSearchMatch]) -> None:
        self._fts_matches = fts_matches

    async def search_fts(self, recall: ContextFtsRecall) -> list[ContextSearchMatch]:
        return self._fts_matches[: recall.recall_filter.limit]

    async def search_vector(
        self, recall: ContextVectorRecall
    ) -> list[ContextSearchMatch]:
        raise AssertionError("vector search is supplied by the embedding collaborator")

    async def chunks_missing_embeddings(
        self,
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        limit: int,
        force: bool = False,
    ) -> list[ContextChunkRecord]:
        return []

    async def embedding_index_status(
        self,
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
    ) -> RagHealthState:
        return RagHealthState.HEALTHY

    async def embedding_source_status(
        self,
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        current_fingerprint: JSONObject,
    ) -> ContextEmbeddingSourceStatus:
        raise AssertionError("not used")

    async def update_chunk_embeddings(
        self,
        updates: list[ContextChunkEmbeddingUpdate],
    ) -> int:
        return 0


class _HybridEmbeddingService:
    def __init__(self, vector_matches: list[ContextSearchMatch]) -> None:
        self._vector_matches = vector_matches

    async def health_with_index_status(self) -> RagDependencyHealth:
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.HEALTHY,
            embedding=RagHealthState.HEALTHY,
            default_strategy=RagStrategy.HYBRID,
            model_name="test",
            dimensions=3,
            fingerprint=None,
            warnings=(),
        )

    async def search_vector(self, **kwargs: object) -> list[ContextSearchMatch]:
        return self._vector_matches


class _UnavailableGraphSignals(IContextGraphSignalProvider):
    async def enrich(
        self, matches: list[ContextSearchMatch]
    ) -> ContextGraphEnrichmentResult:
        raise RuntimeError(
            "graph unavailable at neo4j://reader:super-secret@example.test"
        )


class _ChangedGraphScoreSignals(IContextGraphSignalProvider):
    async def enrich(
        self, matches: list[ContextSearchMatch]
    ) -> ContextGraphEnrichmentResult:
        return ContextGraphEnrichmentResult(
            matches=(replace(matches[0], fts_score=0.01), *matches[1:]),
        )


def test_hybrid_scores_and_order_survive_unavailable_graph_lane() -> None:
    fts_matches = [_match("decision", score=0.9), _match("skill", score=0.8)]
    vector_matches = [_match("skill", score=0.95), _match("decision", score=0.7)]

    baseline = anyio.run(
        _search,
        fts_matches,
        vector_matches,
        ObsidianGraphContextSignalService(repository=None),
    )
    degraded = anyio.run(
        _search,
        fts_matches,
        vector_matches,
        _UnavailableGraphSignals(),
    )

    assert [match.context.id for match in degraded.matches] == [
        match.context.id for match in baseline.matches
    ]
    assert [match.score for match in degraded.matches] == [
        match.score for match in baseline.matches
    ]
    assert baseline.warnings == ()
    assert all(not match.graph_evidence for match in baseline.matches)
    assert "graph_evidence" not in baseline.context_pack
    assert degraded.effective_strategy is RagStrategy.HYBRID
    assert degraded.warnings == (
        "Graph context lane unavailable "
        "[GRAPH_CONTEXT_UNAVAILABLE; RuntimeError]; "
        "primary Context recall preserved.",
    )
    assert "super-secret" not in " ".join(degraded.warnings)
    assert "neo4j://" not in " ".join(degraded.warnings)


def test_available_graph_lane_explains_lineage_and_curation_evidence() -> None:
    repository = FakeObsidianGraphProjectionRepository()
    anyio.run(_replace_projection, repository, _projection())
    provider = ObsidianGraphContextSignalService(repository=repository)

    pack = anyio.run(
        _search,
        [_match("decision", score=0.9), _match("skill", score=0.8)],
        [_match("skill", score=0.95), _match("decision", score=0.7)],
        provider,
    )

    decision = next(match for match in pack.matches if match.context.id == "decision")
    assert [evidence.signal for evidence in decision.graph_evidence] == ["lineage"]
    assert decision.score == pack.matches[0].score
    assert "graph lineage" in decision.why_retrieved
    assert "graph://decision/derived_from/skill" in pack.context_pack
    assert "Legacy" not in pack.context_pack
    assert "graph://decision/supersedes/legacy" not in pack.context_pack
    assert "- graph_evidence:" in pack.context_pack
    assert [item["signal"] for item in match_payload(decision)["graph_evidence"]] == [
        "lineage"
    ]


def test_graph_lane_cannot_change_component_scores_or_primary_strategy() -> None:
    fts_matches = [_match("decision", score=0.9), _match("skill", score=0.8)]
    vector_matches = [_match("skill", score=0.95), _match("decision", score=0.7)]

    baseline = anyio.run(
        _search,
        fts_matches,
        vector_matches,
        ObsidianGraphContextSignalService(repository=None),
    )
    pack = anyio.run(
        _search,
        fts_matches,
        vector_matches,
        _ChangedGraphScoreSignals(),
    )

    assert pack.strategy is RagStrategy.HYBRID
    assert pack.effective_strategy is RagStrategy.HYBRID
    assert [match.context.id for match in pack.matches] == [
        match.context.id for match in baseline.matches
    ]
    assert [match.score for match in pack.matches] == [
        match.score for match in baseline.matches
    ]
    assert [match.fts_score for match in pack.matches] == [
        match.fts_score for match in baseline.matches
    ]
    assert pack.warnings == (
        "Graph context lane returned invalid ranking; "
        "primary Context recall preserved.",
    )


def test_graph_lane_derives_duplicate_impact_and_resume_curation_signals() -> None:
    repository = FakeObsidianGraphProjectionRepository()
    anyio.run(_replace_projection, repository, _curation_projection())
    provider = ObsidianGraphContextSignalService(repository=repository)

    result = anyio.run(
        provider.enrich,
        [
            _match("decision", score=0.9),
            _match("duplicate", score=0.8),
            _match("bug", score=0.7),
            _match("resume", score=0.6),
        ],
    )

    assert [item.signal for item in result.matches[0].graph_evidence] == [
        "duplicate_candidate",
        "resume_path",
        "impact_analysis",
    ]


def test_graph_lane_does_not_disclose_outside_result_target_metadata() -> None:
    repository = FakeObsidianGraphProjectionRepository()
    projection = ObsidianGraphProjection(
        nodes=(
            _node("decision", AlexandriaNoteType.CONTEXT),
            ObsidianGraphProjectionNode(
                note_id="outside-scope",
                relative_path="Contexts/Private/outside-scope.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="PRIVATE CUSTOMER CREDENTIAL ROTATION",
                status="current",
                project="other-project",
            ),
        ),
        edges=(
            _edge(
                "decision",
                "outside-scope",
                ObsidianRelationType.SUPERSEDES,
            ),
        ),
    )
    anyio.run(_replace_projection, repository, projection)

    result = anyio.run(
        ObsidianGraphContextSignalService(repository=repository).enrich,
        [_match("decision", score=0.9)],
    )

    recalled = result.matches[0]
    assert recalled.graph_evidence == ()
    assert recalled.why_retrieved == "SQLite retrieval evidence."
    assert "outside-scope" not in recalled.why_retrieved
    assert "PRIVATE CUSTOMER" not in recalled.why_retrieved


def test_graph_lane_cannot_reintroduce_cross_project_match_after_scope_filter() -> None:
    repository = FakeObsidianGraphProjectionRepository()
    projection = ObsidianGraphProjection(
        nodes=(
            _node("decision", AlexandriaNoteType.CONTEXT),
            ObsidianGraphProjectionNode(
                note_id="foreign",
                relative_path="Contexts/Other/foreign.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="FOREIGN PRIVATE ROADMAP",
                status="current",
                project="other-project",
            ),
        ),
        edges=(_edge("decision", "foreign", ObsidianRelationType.DERIVED_FROM),),
    )
    anyio.run(_replace_projection, repository, projection)
    provider = ObsidianGraphContextSignalService(repository=repository)
    foreign = _match("foreign", score=0.95, project="other-project")

    pack = anyio.run(
        _search,
        [_match("decision", score=0.9), foreign],
        [foreign, _match("decision", score=0.7)],
        provider,
    )

    assert [match.context.id for match in pack.matches] == ["decision"]
    assert pack.matches[0].graph_evidence == ()
    assert "foreign" not in pack.context_pack.lower()
    assert "PRIVATE ROADMAP" not in pack.context_pack


@pytest.mark.parametrize(
    ("relation", "signal"),
    [
        (ObsidianRelationType.DERIVED_FROM, "lineage"),
        (ObsidianRelationType.SUPERSEDES, "supersedes_candidate"),
        (ObsidianRelationType.BLOCKS, "impact_analysis"),
        (ObsidianRelationType.RESOLVES, "impact_analysis"),
    ],
)
def test_directional_curation_relations_preserve_both_endpoint_semantics(
    relation: ObsidianRelationType,
    signal: str,
) -> None:
    repository = FakeObsidianGraphProjectionRepository()
    anyio.run(
        _replace_projection,
        repository,
        ObsidianGraphProjection(
            nodes=(
                _node("source", AlexandriaNoteType.CONTEXT),
                _node("target", AlexandriaNoteType.CONTEXT),
            ),
            edges=(_edge("source", "target", relation),),
        ),
    )

    result = anyio.run(
        ObsidianGraphContextSignalService(repository=repository).enrich,
        [_match("source", score=0.9), _match("target", score=0.8)],
    )

    outgoing = result.matches[0].graph_evidence[0]
    incoming = result.matches[1].graph_evidence[0]
    assert outgoing.signal == signal
    assert incoming.signal == signal
    assert outgoing.direction is ContextGraphDirection.OUTGOING
    assert incoming.direction is ContextGraphDirection.INCOMING
    assert outgoing.source_context_id == incoming.source_context_id == "source"
    assert outgoing.target_context_id == incoming.target_context_id == "target"
    assert "direction=outgoing" in result.matches[0].why_retrieved
    assert "direction=incoming" in result.matches[1].why_retrieved


async def _search(
    fts_matches: list[ContextSearchMatch],
    vector_matches: list[ContextSearchMatch],
    graph_signals: IContextGraphSignalProvider | None,
) -> ContextPack:
    service = ContextSearchService(
        search_sources=[_HybridSearchSource(fts_matches)],
        embedding_service=cast(
            ContextEmbeddingService,
            _HybridEmbeddingService(vector_matches),
        ),
        graph_signal_provider=graph_signals,
    )
    return await service.search(
        "resume decision lineage",
        strategy=RagStrategy.HYBRID,
        project="heterarchy-alexandria",
        limit=5,
    )


async def _replace_projection(
    repository: FakeObsidianGraphProjectionRepository,
    projection: ObsidianGraphProjection,
) -> None:
    await repository.start_rebuild(run_id="g005-test", projection_version=1)
    await repository.write_rebuild_batch(
        run_id="g005-test",
        projection_version=1,
        batch=projection,
    )
    await repository.complete_rebuild(run_id="g005-test", projection_version=1)


def _match(
    note_id: str,
    *,
    score: float,
    project: str = "heterarchy-alexandria",
) -> ContextSearchMatch:
    context = ContextRecord(
        id=note_id,
        kind=ContextKind.HANDOFF,
        title=note_id.title(),
        summary="summary",
        content="content",
        content_format=ContextContentFormat.MARKDOWN,
        project=project,
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
        context_metadata=ContextMetadataPayload(canonical_context_id=note_id),
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )
    chunk = ContextChunkRecord(
        id=f"chunk-{note_id}",
        context_id=note_id,
        chunk_index=0,
        heading=None,
        content="content",
        token_count=1,
        content_hash=f"hash-{note_id}",
        chunk_metadata=ContextMetadataPayload(),
        created_at=NOW,
    )
    return ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=score,
        fts_score=score,
        vector_score=score,
        why_retrieved="SQLite retrieval evidence.",
    )


def _projection() -> ObsidianGraphProjection:
    nodes = tuple(
        ObsidianGraphProjectionNode(
            note_id=note_id,
            relative_path=f"Contexts/{note_id}.md",
            alexandria_type=note_type,
            title=note_id.title(),
            status="current",
            project="heterarchy-alexandria",
        )
        for note_id, note_type in (
            ("decision", AlexandriaNoteType.CONTEXT),
            ("skill", AlexandriaNoteType.SKILL),
            ("legacy", AlexandriaNoteType.CONTEXT),
        )
    )
    edges = (
        _edge("decision", "skill", ObsidianRelationType.DERIVED_FROM),
        _edge("decision", "legacy", ObsidianRelationType.SUPERSEDES),
    )
    return ObsidianGraphProjection(nodes=nodes, edges=edges)


def _node(
    note_id: str,
    note_type: AlexandriaNoteType,
) -> ObsidianGraphProjectionNode:
    return ObsidianGraphProjectionNode(
        note_id=note_id,
        relative_path=f"Contexts/{note_id}.md",
        alexandria_type=note_type,
        title=note_id.title(),
        status="current",
        project="heterarchy-alexandria",
    )


def _curation_projection() -> ObsidianGraphProjection:
    nodes = tuple(
        ObsidianGraphProjectionNode(
            note_id=note_id,
            relative_path=f"Contexts/{note_id}.md",
            alexandria_type=note_type,
            title=note_id.title(),
            status="current",
            project="heterarchy-alexandria",
        )
        for note_id, note_type in (
            ("decision", AlexandriaNoteType.CONTEXT),
            ("duplicate", AlexandriaNoteType.CONTEXT),
            ("bug", AlexandriaNoteType.CONTEXT),
            ("resume", AlexandriaNoteType.JOB_PLAN),
        )
    )
    edges = (
        _edge("decision", "duplicate", ObsidianRelationType.DUPLICATES),
        _edge("decision", "bug", ObsidianRelationType.RESOLVES),
        _edge("decision", "resume", ObsidianRelationType.RELATED),
    )
    return ObsidianGraphProjection(nodes=nodes, edges=edges)


def _edge(
    source: str,
    target: str,
    relation: ObsidianRelationType,
) -> ObsidianGraphProjectionEdge:
    return ObsidianGraphProjectionEdge(
        edge_id=f"{source}:{relation.value}:{target}",
        source_note_id=source,
        source_path=f"Contexts/{source}.md",
        target_note_id=target,
        target_path=f"Contexts/{target}.md",
        relation=relation,
        confidence=1.0,
        source_kind=ObsidianEdgeSourceKind.FRONTMATTER,
    )
