"""Contract tests for the Rust active-projection graph candidate selector."""

from __future__ import annotations

import orjson

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionNode,
    ObsidianGraphTraversalRequest,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphTraversalDirection,
)
from app.obsidian.infrastructure.graph.native_obsidian_graph_candidate_selection_compute_provider import (
    NativeObsidianGraphCandidateSelectionComputeProvider,
)


class _FakeNativeModule:
    def compute_contract_version(self) -> int:
        return 1

    def native_package_version(self) -> str:
        return "0.1.0"

    def native_git_revision(self) -> str:
        return "test"

    def native_build_profile(self) -> str:
        return "test"

    def feature_authority_schema_version(self) -> int:
        return 1

    def select_graph_projection_candidates_json(self, payload: bytes) -> bytes:
        request = orjson.loads(payload)
        traversal = request["traversal_requests"][0]
        return orjson.dumps(
            {
                "contract_version": 1,
                "graph_compute_version": 1,
                "traversals": [
                    {
                        "request_id": traversal["request_id"],
                        "start_note_id": traversal["start_note_id"],
                        "start_found": True,
                        "visits": [
                            {"note_id": traversal["start_note_id"], "depth": 0},
                            {"note_id": "middle", "depth": 1},
                            {"note_id": "target", "depth": 2},
                        ],
                        "truncated": False,
                    }
                ],
                "candidates": [
                    {
                        "note_id": "target",
                        "min_depth": 2,
                        "seed_support": 1,
                        "shared_title_trigrams": 5,
                        "title_trigram_union": 10,
                        "path_hops": [
                            {
                                "edge_id": "edge-1",
                                "source_note_id": "seed",
                                "target_note_id": "middle",
                                "relation": "wikilink",
                                "direction": "outgoing",
                                "depth": 1,
                            },
                            {
                                "edge_id": "edge-2",
                                "source_note_id": "middle",
                                "target_note_id": "target",
                                "relation": "wikilink",
                                "direction": "outgoing",
                                "depth": 2,
                            },
                        ],
                    }
                ],
                "primary_title_relevance": [
                    {
                        "note_id": "seed",
                        "shared_title_trigrams": 3,
                        "title_trigram_union": 12,
                    }
                ],
            }
        )


class _InvalidCandidateNativeModule(_FakeNativeModule):
    def select_graph_projection_candidates_json(self, payload: bytes) -> bytes:
        value = orjson.loads(super().select_graph_projection_candidates_json(payload))
        value["candidates"][0]["note_id"] = "outside-projection"
        value["candidates"][0]["path_hops"][-1]["target_note_id"] = "outside-projection"
        return orjson.dumps(value)


def _projection() -> ObsidianGraphProjection:
    return ObsidianGraphProjection(
        nodes=(
            ObsidianGraphProjectionNode(
                note_id="seed",
                relative_path="Contexts/seed.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="Migration Plan",
                status="active",
                project="heterarchy-alexandria",
            ),
            ObsidianGraphProjectionNode(
                note_id="middle",
                relative_path="Contexts/middle.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="Migration Working Notes",
                status="active",
                project="heterarchy-alexandria",
            ),
            ObsidianGraphProjectionNode(
                note_id="target",
                relative_path="Contexts/target.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="Runtime Seal Verification",
                status="active",
                project="heterarchy-alexandria",
            ),
        ),
        edges=(
            ObsidianGraphProjectionEdge(
                edge_id="edge-1",
                source_note_id="seed",
                source_path="Contexts/seed.md",
                target_note_id="middle",
                target_path="Contexts/middle.md",
                relation=ObsidianRelationType.WIKILINK,
                confidence=1.0,
                source_kind=ObsidianEdgeSourceKind.WIKILINK,
            ),
            ObsidianGraphProjectionEdge(
                edge_id="edge-2",
                source_note_id="middle",
                source_path="Contexts/middle.md",
                target_note_id="target",
                target_path="Contexts/target.md",
                relation=ObsidianRelationType.WIKILINK,
                confidence=1.0,
                source_kind=ObsidianEdgeSourceKind.WIKILINK,
            ),
        ),
    )


def _request() -> ObsidianGraphTraversalRequest:
    return ObsidianGraphTraversalRequest(
        request_id="case-1",
        start_note_id="seed",
        direction=ObsidianGraphTraversalDirection.BOTH,
        relations=("wikilink",),
        max_depth=2,
        max_results=50,
    )


def test_native_graph_candidate_selector_preserves_bounded_rust_evidence() -> None:
    provider = NativeObsidianGraphCandidateSelectionComputeProvider(_FakeNativeModule())

    result = provider.select_candidates(
        _projection(),
        (_request(),),
        primary_note_ids=("seed",),
        query="runtime seal status",
        max_candidates=3,
        min_shared_trigrams=3,
    )

    assert provider.authority == "rust:graph_compute:candidate_selection:v1"
    assert len(result.traversals) == 1
    assert result.traversals[0].request_id == "case-1"
    assert [(visit.note_id, visit.depth) for visit in result.traversals[0].visits] == [
        ("seed", 0),
        ("middle", 1),
        ("target", 2),
    ]
    assert len(result.candidates) == 1
    assert result.candidates[0].note_id == "target"
    assert result.candidates[0].min_depth == 2
    assert result.candidates[0].shared_title_trigrams == 5
    assert result.candidates[0].title_trigram_union == 10
    assert [
        (hop.edge_id, hop.source_note_id, hop.target_note_id, hop.depth)
        for hop in result.candidates[0].path_hops
    ] == [
        ("edge-1", "seed", "middle", 1),
        ("edge-2", "middle", "target", 2),
    ]
    assert result.primary_title_relevance[0].note_id == "seed"


def test_native_graph_candidate_selector_fails_closed_on_external_candidate() -> None:
    provider = NativeObsidianGraphCandidateSelectionComputeProvider(
        _InvalidCandidateNativeModule()
    )

    try:
        provider.select_candidates(
            _projection(),
            (_request(),),
            primary_note_ids=("seed",),
            query="runtime seal status",
            max_candidates=3,
            min_shared_trigrams=3,
        )
    except ValueError as exc:
        assert "candidate missing from projection" in str(exc)
    else:
        raise AssertionError(
            "graph candidate outside active projection must fail closed"
        )
