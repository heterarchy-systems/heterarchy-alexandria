"""Contract tests for the active-projection Rust graph traversal adapter."""

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
from app.obsidian.infrastructure.graph.native_obsidian_graph_traversal_compute_provider import (
    NativeObsidianGraphTraversalComputeProvider,
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

    def traverse_graph_projection_json(self, payload: bytes) -> bytes:
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
                            {"note_id": "target", "depth": 2},
                        ],
                        "truncated": False,
                    }
                ],
            }
        )


class _WrongIdentityNativeModule(_FakeNativeModule):
    def traverse_graph_projection_json(self, payload: bytes) -> bytes:
        _ = payload
        return orjson.dumps(
            {
                "contract_version": 1,
                "graph_compute_version": 1,
                "traversals": [
                    {
                        "request_id": "wrong",
                        "start_note_id": "wrong",
                        "start_found": True,
                        "visits": [],
                        "truncated": False,
                    }
                ],
            }
        )


def _projection() -> ObsidianGraphProjection:
    return ObsidianGraphProjection(
        nodes=(
            ObsidianGraphProjectionNode(
                note_id="seed",
                relative_path="Contexts/seed.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="Seed",
                status="active",
                project="heterarchy-alexandria",
            ),
            ObsidianGraphProjectionNode(
                note_id="target",
                relative_path="Contexts/target.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="Target",
                status="active",
                project="heterarchy-alexandria",
            ),
        ),
        edges=(
            ObsidianGraphProjectionEdge(
                edge_id="edge-1",
                source_note_id="seed",
                source_path="Contexts/seed.md",
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
        max_results=10,
    )


def test_native_graph_traversal_adapter_preserves_identity_depth_and_authority() -> (
    None
):
    provider = NativeObsidianGraphTraversalComputeProvider(_FakeNativeModule())

    results = provider.traverse(_projection(), (_request(),))

    assert provider.authority == "rust:graph_compute:traversal:v1"
    assert len(results) == 1
    assert results[0].request_id == "case-1"
    assert results[0].start_note_id == "seed"
    assert [(visit.note_id, visit.depth) for visit in results[0].visits] == [
        ("seed", 0),
        ("target", 2),
    ]
    assert results[0].truncated is False


def test_native_graph_traversal_adapter_fails_closed_on_identity_mismatch() -> None:
    provider = NativeObsidianGraphTraversalComputeProvider(_WrongIdentityNativeModule())

    try:
        provider.traverse(_projection(), (_request(),))
    except ValueError as exc:
        assert "result identity mismatch" in str(exc)
    else:
        raise AssertionError(
            "native graph traversal identity mismatch must fail closed"
        )
