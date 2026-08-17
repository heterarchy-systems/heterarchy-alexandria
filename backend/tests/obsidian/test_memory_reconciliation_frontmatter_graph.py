"""Obsidian round-trip tests for memory reconciliation metadata and graph edges."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.domain.event_enum.context_enums import ContextKind
from app.obsidian.application.graph.obsidian_graph_edge_builder import (
    relation_edges_from_note,
)
from app.obsidian.application.graph.obsidian_graph_link_renderer import (
    add_or_update_alexandria_links_section,
)
from app.obsidian.application.notes.obsidian_context_frontmatter_mapper import (
    context_content_hash,
    context_identity_from_frontmatter,
    normalized_context_frontmatter,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)

NOW = datetime(2026, 7, 25, tzinfo=UTC)
EARLIER = datetime(2026, 7, 1, tzinfo=UTC)


def test_reconciliation_temporal_frontmatter_round_trips() -> None:
    body = "heterarchy-alexandria uses PostgreSQL."
    content_hash = context_content_hash(body)
    identity = context_identity_from_frontmatter(
        {
            "scope": "PROJECT",
            "project": "heterarchy-alexandria",
            "visibility": "PROJECT",
            "status": "active",
            "source_actor_id": "memory-reconciliation",
            "source_actor_type": "SYSTEM",
            "content_hash": content_hash,
            "version": 1,
            "context_kind": ContextKind.MEMORY.value,
            "created_at": EARLIER.isoformat(),
            "updated_at": NOW.isoformat(),
            "recorded_at": NOW.isoformat(),
            "observed_at": EARLIER.isoformat(),
            "valid_from": EARLIER.isoformat(),
            "valid_to": None,
            "reconciliation_candidate_id": "candidate-1",
            "conflict_set_ids": ["conflict-1", "conflict-2"],
        },
        project="heterarchy-alexandria",
        status="active",
        generated_content_hash=content_hash,
    )

    assert identity.recorded_at == NOW
    assert identity.observed_at == EARLIER
    assert identity.valid_from == EARLIER
    assert identity.valid_to is None
    assert identity.reconciliation_candidate_id == "candidate-1"
    assert identity.conflict_set_ids == ("conflict-1", "conflict-2")

    normalized = normalized_context_frontmatter(identity)
    assert normalized["recorded_at"] == NOW.isoformat()
    assert normalized["observed_at"] == EARLIER.isoformat()
    assert normalized["valid_from"] == EARLIER.isoformat()
    assert normalized["valid_to"] is None
    assert normalized["reconciliation_candidate_id"] == "candidate-1"
    assert normalized["conflict_set_ids"] == ["conflict-1", "conflict-2"]


def test_reconciliation_graph_relations_parse_and_render_all_official_types() -> None:
    frontmatter = {
        "duplicates": [{"id": "ctx-duplicate", "path": "Contexts/Duplicate.md"}],
        "supports": [{"id": "ctx-support", "path": "Contexts/Support.md"}],
        "extends": [{"id": "ctx-extension", "path": "Contexts/Extension.md"}],
        "contradicts": [{"id": "ctx-conflict", "path": "Contexts/Conflict.md"}],
        "supersedes": [{"id": "ctx-old", "path": "Contexts/Old.md"}],
    }

    edges = relation_edges_from_note(
        note_id="ctx-current",
        relative_path="Alexandria/Contexts/Current.md",
        alexandria_root="Alexandria",
        frontmatter=frontmatter,
        body="Current memory.",
    )

    assert {
        (edge.target_note_id, edge.relation, edge.source_kind) for edge in edges
    } == {
        (
            "ctx-duplicate",
            ObsidianRelationType.DUPLICATES,
            ObsidianEdgeSourceKind.FRONTMATTER,
        ),
        (
            "ctx-support",
            ObsidianRelationType.SUPPORTS,
            ObsidianEdgeSourceKind.FRONTMATTER,
        ),
        (
            "ctx-extension",
            ObsidianRelationType.EXTENDS,
            ObsidianEdgeSourceKind.FRONTMATTER,
        ),
        (
            "ctx-conflict",
            ObsidianRelationType.CONTRADICTS,
            ObsidianEdgeSourceKind.FRONTMATTER,
        ),
        (
            "ctx-old",
            ObsidianRelationType.SUPERSEDES,
            ObsidianEdgeSourceKind.FRONTMATTER,
        ),
    }

    rendered = add_or_update_alexandria_links_section("# Current\n", frontmatter)
    assert "### Duplicates" in rendered
    assert "### Supports" in rendered
    assert "### Extends" in rendered
    assert "### Contradicts" in rendered
    assert "### Supersedes" in rendered
    assert "[[Contexts/Conflict]] — contradicts" in rendered
