"""Obsidian graph relation parsing behavior tests."""

from __future__ import annotations

from app.obsidian.application.graph.diagnostics.obsidian_graph_link_renderer import (
    add_or_update_alexandria_links_section,
)
from app.obsidian.application.graph.relations.native_obsidian_graph_edge_builder import (
    create_native_obsidian_graph_edge_builder,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)


def test_graph_relations_parse_frontmatter_and_wikilinks() -> None:
    """Frontmatter relations and body wikilinks should become rebuildable edges."""
    edges = create_native_obsidian_graph_edge_builder().build(
        note_id="ctx_current",
        relative_path="Alexandria/Contexts/Current.md",
        alexandria_root="Alexandria",
        frontmatter={
            "source_refs": [
                {
                    "id": "alexandria_start_here",
                    "path": "START_HERE.md",
                    "relation": "cites",
                }
            ],
            "related": ["Skills/Active/Web Research.md"],
        },
        body="Read [[Prompts/System/Research|research prompt]] and [[START_HERE]].",
    )

    actual = sorted(
        [
            (edge.target_note_id, edge.target_path, edge.relation, edge.source_kind)
            for edge in edges
        ],
        key=lambda item: (item[1], item[2].value, item[3].value, item[0] or ""),
    )
    assert actual == [
        (
            None,
            "Alexandria/Prompts/System/Research.md",
            ObsidianRelationType.WIKILINK,
            ObsidianEdgeSourceKind.WIKILINK,
        ),
        (
            "alexandria_start_here",
            "Alexandria/START_HERE.md",
            ObsidianRelationType.CITES,
            ObsidianEdgeSourceKind.FRONTMATTER,
        ),
        (
            None,
            "Alexandria/START_HERE.md",
            ObsidianRelationType.WIKILINK,
            ObsidianEdgeSourceKind.WIKILINK,
        ),
        (
            None,
            "Alexandria/Skills/Active/Web Research.md",
            ObsidianRelationType.RELATED,
            ObsidianEdgeSourceKind.FRONTMATTER,
        ),
    ]


def test_graph_relations_parse_legacy_inline_json_source_refs() -> None:
    """Legacy JSON metadata must remain one relation instead of comma fragments."""
    from app.obsidian.infrastructure.markdown.frontmatter import (
        frontmatter_json,
        parse_markdown_document,
    )

    document = parse_markdown_document(
        "---\n"
        "alexandria_type: memory_compact\n"
        'source_refs: [{"id":"ref-1","source_type":"obsidian_note",'
        '"source_id":"ctx-source","detail_path":"Contexts/Source.md"}]\n'
        "---\n\n# Compact\n"
    )

    edges = create_native_obsidian_graph_edge_builder().build(
        note_id="compact-current",
        relative_path="Alexandria/Memory Compacts/Current.md",
        alexandria_root="Alexandria",
        frontmatter=frontmatter_json(document.frontmatter),
        body=document.body,
    )

    assert [
        (edge.target_note_id, edge.target_path, edge.relation) for edge in edges
    ] == [
        (
            "ctx-source",
            "Alexandria/Contexts/Source.md",
            ObsidianRelationType.CITES,
        )
    ]


def test_graph_relations_treat_explicit_empty_source_ref_links_as_no_graph_cites() -> (
    None
):
    """Structured source metadata should not become graph edges after link migration."""
    edges = create_native_obsidian_graph_edge_builder().build(
        note_id="compact-current",
        relative_path="Memory Compacts/Current.md",
        alexandria_root=".",
        frontmatter={
            "source_refs": [
                {
                    "source_id": "external-run",
                    "detail_path": "operations/readiness/2026-07-31.md",
                }
            ],
            "source_ref_links": [],
        },
        body="# Compact\n",
    )

    assert edges == []


def test_graph_relations_ignore_wikilinks_in_comments_and_code() -> None:
    """Only rendered Markdown links should become graph relations."""
    edges = create_native_obsidian_graph_edge_builder().build(
        note_id="ctx-current",
        relative_path="Alexandria/Contexts/Projects/Current.md",
        alexandria_root="Alexandria",
        frontmatter={},
        body=(
            "Visible [[Contexts/Source]].\n"
            "`inline [[Inline Example]]`\n"
            "<!-- [[HTML Comment]] -->\n"
            "%% [[Obsidian Comment]] %%\n"
            "```md\n[[Fenced Example]]\n```\n"
        ),
    )

    assert [edge.target_path for edge in edges] == ["Alexandria/Contexts/Source.md"]


def test_graph_relations_ignore_external_evidence_and_artifact_identifiers() -> None:
    """Provenance identifiers are not Obsidian note paths or graph nodes."""
    edges = create_native_obsidian_graph_edge_builder().build(
        note_id="trade-journal",
        relative_path="Contexts/Projects/Trader/Journal.md",
        alexandria_root=".",
        frontmatter={
            "source_refs": ["evidence:run-123:1", "artifact:report-456"],
        },
        body=(
            "Evidence [[evidence:run-123:1]] and "
            "artifact [[artifact:report-456]] are external identifiers.\n"
            "The real note link is [[Contexts/Projects/Trader/Index]].\n"
        ),
    )

    assert [edge.target_path for edge in edges] == ["Contexts/Projects/Trader/Index.md"]


def test_graph_relations_keep_vault_root_targets_when_root_is_dot() -> None:
    """Root-vault installs should not treat the first folder as Alexandria root."""
    edges = create_native_obsidian_graph_edge_builder().build(
        note_id="ctx_current",
        relative_path="Contexts/Current.md",
        alexandria_root=".",
        frontmatter={
            "source_refs": [
                {
                    "id": "alexandria_start_here",
                    "path": "START_HERE.md",
                    "relation": "cites",
                }
            ],
        },
        body="Read [[START_HERE]].",
    )

    actual = sorted(
        [
            (edge.target_note_id, edge.target_path, edge.relation, edge.source_kind)
            for edge in edges
        ],
        key=lambda item: (item[1], item[2].value, item[3].value, item[0] or ""),
    )
    assert actual == [
        (
            "alexandria_start_here",
            "START_HERE.md",
            ObsidianRelationType.CITES,
            ObsidianEdgeSourceKind.FRONTMATTER,
        ),
        (
            None,
            "START_HERE.md",
            ObsidianRelationType.WIKILINK,
            ObsidianEdgeSourceKind.WIKILINK,
        ),
    ]


def test_alexandria_links_section_updates_marker_without_touching_user_body() -> None:
    """Generated graph wikilinks should only replace the managed marker block."""
    body = "# Note\n\nUser paragraph.\n\n<!-- ALEXANDRIA-LINKS:START -->\nold\n<!-- ALEXANDRIA-LINKS:END -->\n"

    updated = add_or_update_alexandria_links_section(
        body,
        {
            "source_refs": [
                {"path": "START_HERE.md", "relation": "cites"},
            ]
        },
    )

    assert "User paragraph." in updated
    assert "old" not in updated
    assert "[[START_HERE]] — cites" in updated
