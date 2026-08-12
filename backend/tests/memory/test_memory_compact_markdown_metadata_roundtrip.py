"""Memory Compact Markdown metadata type round-trip tests."""

from __future__ import annotations

from pathlib import Path

from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_parser import (
    _read_frontmatter,
    read_compact_file,
)
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_serializer import (
    _yaml_property_lines,
    _yaml_scalar,
)


def test_memory_compact_frontmatter_preserves_collection_metadata_types() -> None:
    """Block and inline YAML collections should parse as string tuples."""
    block_frontmatter, _ = _read_frontmatter(
        """---
alexandria_type: memory_compact
tags:
  - Alexandria
  - 'memory-compact'
---
Body
"""
    )
    inline_frontmatter, _ = _read_frontmatter(
        """---
alexandria_type: memory_compact
tags: [Alexandria, 'memory-compact']
---
Body
"""
    )

    assert block_frontmatter["tags"] == ("Alexandria", "memory-compact")
    assert inline_frontmatter["tags"] == ("Alexandria", "memory-compact")


def test_memory_compact_frontmatter_preserves_boolean_metadata_types() -> None:
    """Boolean metadata should remain Boolean through render and parse."""
    rendered_true = _yaml_scalar(True)
    rendered_false = _yaml_scalar(False)
    frontmatter, _ = _read_frontmatter(
        f"""---
alexandria_type: memory_compact
source_of_truth: {rendered_true}
requires_review: {rendered_false}
---
Body
"""
    )

    assert rendered_true == "true"
    assert rendered_false == "false"
    assert frontmatter["source_of_truth"] is True
    assert frontmatter["requires_review"] is False


def test_memory_compact_frontmatter_collection_render_parse_round_trip() -> None:
    """Rendered string collections should parse back without stringification."""
    rendered_tag_lines = _yaml_property_lines("tags", ("alpha", "beta"))
    rendered_tags = "\n".join(rendered_tag_lines)
    frontmatter, _ = _read_frontmatter(
        f"""---
alexandria_type: memory_compact
{rendered_tags}
---
Body
"""
    )

    assert rendered_tag_lines == ["tags:", "  - 'alpha'", "  - 'beta'"]
    assert frontmatter["tags"] == ("alpha", "beta")


def test_memory_compact_parser_accepts_legacy_block_list_source_refs(
    tmp_path: Path,
) -> None:
    """Legacy JSON-object string lists should restore structured source refs."""
    note_path = tmp_path / "legacy-compact.md"
    note_path.write_text(
        """---
alexandria_type: memory_compact
id: legacy-compact
status: CURRENT
project: alexandria-hermes
created_at: 2026-08-01T00:00:00Z
updated_at: 2026-08-01T00:00:00Z
covered_from: 2026-07-01T00:00:00Z
covered_to: 2026-07-31T00:00:00Z
source_refs:
  - '{"id":"ref-1","compact_id":"legacy-compact","source_type":"obsidian","source_id":"source-1","title":"Source One","detail_path":"Contexts/Source One.md","source_hash":null}'
  - '{"id":"ref-2","source_type":"memory_compact","source_id":"source-2","title":"Source Two","detail_path":"id:source-2","source_hash":null}'
---
# Legacy Compact
""",
        encoding="utf-8",
    )

    compact = read_compact_file(note_path)

    assert compact is not None
    assert [(ref.id, ref.compact_id, ref.source_id) for ref in compact.source_refs] == [
        ("ref-1", "legacy-compact", "source-1"),
        ("ref-2", "legacy-compact", "source-2"),
    ]
