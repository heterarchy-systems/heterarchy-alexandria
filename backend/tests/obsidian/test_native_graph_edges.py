"""Native Obsidian graph edge adapter contracts."""

from __future__ import annotations

import json

from app.obsidian.application.graph.relations.native_obsidian_graph_edge_builder import (
    NativeObsidianGraphEdgeBuilder,
    create_native_obsidian_graph_edge_builder,
)


class _FakeReferenceModule:
    def compute_contract_version(self) -> int:
        return 1

    def extract_reference_batch_json(self, payload: bytes) -> bytes:
        request = json.loads(payload)
        document = request["documents"][0]
        assert document["frontmatter_edges"][0] == {
            "target_path": "START_HERE.md",
            "target_note_id": "start",
            "relation": "cites",
            "source_field": "source_refs",
        }
        return json.dumps(
            {
                "contract_version": 1,
                "extraction_version": 1,
                "results": [
                    {
                        "note_id": document["note_id"],
                        "relative_path": document["relative_path"],
                        "references": [],
                        "warnings": [],
                        "edges": [
                            {
                                "edge_id": "a" * 64,
                                "source_note_id": document["note_id"],
                                "source_path": document["relative_path"],
                                "target_note_id": "start",
                                "target_path": "Alexandria/START_HERE.md",
                                "relation": "cites",
                                "source_kind": "frontmatter",
                                "confidence": 1.0,
                                "identity_material": "material",
                                "reference_index": None,
                            }
                        ],
                    }
                ],
            }
        ).encode()


def test_native_edge_builder_keeps_relation_policy_in_python() -> None:
    edges = NativeObsidianGraphEdgeBuilder(_FakeReferenceModule()).build(
        note_id="current",
        relative_path="Alexandria/Contexts/Current.md",
        alexandria_root="Alexandria",
        frontmatter={
            "source_refs": [
                {"id": "start", "path": "START_HERE.md", "relation": "cites"}
            ]
        },
        body="# Current\n",
    )

    assert len(edges) == 1
    assert edges[0].edge_id == "a" * 64
    assert edges[0].target_path == "Alexandria/START_HERE.md"
    assert edges[0].relation.value == "cites"
    assert edges[0].source_kind.value == "frontmatter"


def test_frontmatter_policy_preserves_source_ref_links_precedence() -> None:
    class _CaptureModule(_FakeReferenceModule):
        def __init__(self) -> None:
            self.frontmatter_edges: list[dict[str, object]] = []

        def extract_reference_batch_json(self, payload: bytes) -> bytes:
            request = json.loads(payload)
            self.frontmatter_edges = request["documents"][0]["frontmatter_edges"]
            return json.dumps(
                {
                    "contract_version": 1,
                    "extraction_version": 1,
                    "results": [
                        {
                            "note_id": "current",
                            "relative_path": "Current.md",
                            "references": [],
                            "warnings": [],
                            "edges": [],
                        }
                    ],
                }
            ).encode()

    module = _CaptureModule()
    NativeObsidianGraphEdgeBuilder(module).build(
        note_id="current",
        relative_path="Current.md",
        alexandria_root=".",
        frontmatter={
            "source_refs": [{"id": "legacy", "path": "Legacy.md"}],
            "source_ref_links": [],
        },
        body="",
    )

    assert module.frontmatter_edges == []


def test_native_edge_fixture_is_deterministic() -> None:
    edges = create_native_obsidian_graph_edge_builder().build(
        note_id="current",
        relative_path="Alexandria/Contexts/Current.md",
        alexandria_root="Alexandria",
        frontmatter={"related": ["Skills/Active/Web Research.md"]},
        body="Read [[START_HERE]].",
    )

    assert len(edges) == 2
    assert all(len(edge.edge_id) == 64 for edge in edges)
