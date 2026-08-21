"""Shared constants for Obsidian graph relation parsing and rendering."""

from __future__ import annotations

import re

from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianRelationType,
)

ALEXANDRIA_LINKS_START = "<!-- ALEXANDRIA-LINKS:START -->"
ALEXANDRIA_LINKS_END = "<!-- ALEXANDRIA-LINKS:END -->"
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_FRONTMATTER_RELATIONS: tuple[tuple[str, ObsidianRelationType], ...] = (
    ("source_ref_links", ObsidianRelationType.CITES),
    ("source_refs", ObsidianRelationType.CITES),
    ("derived_from", ObsidianRelationType.DERIVED_FROM),
    ("related", ObsidianRelationType.RELATED),
    ("supersedes", ObsidianRelationType.SUPERSEDES),
    ("duplicates", ObsidianRelationType.DUPLICATES),
    ("supports", ObsidianRelationType.SUPPORTS),
    ("extends", ObsidianRelationType.EXTENDS),
    ("contradicts", ObsidianRelationType.CONTRADICTS),
    ("contains", ObsidianRelationType.CONTAINS),
    ("promotes_to", ObsidianRelationType.PROMOTES_TO),
    ("blocks", ObsidianRelationType.BLOCKS),
    ("resolves", ObsidianRelationType.RESOLVES),
)
_ROOT_RELATIVE_LINK_PREFIXES = frozenset(
    {
        "Archive",
        "Contexts",
        "Indexes",
        "Memory Compacts",
        "Prompts",
        "Skills",
        "START_HERE.md",
        "_Inbox",
        "_Ops",
    }
)
_RELATION_HEADINGS: dict[ObsidianRelationType, str] = {
    ObsidianRelationType.CITES: "Sources",
    ObsidianRelationType.RELATED: "Related",
    ObsidianRelationType.DERIVED_FROM: "Derived From",
    ObsidianRelationType.SUPERSEDES: "Supersedes",
    ObsidianRelationType.PROMOTES_TO: "Promotes To",
    ObsidianRelationType.BLOCKS: "Blocks",
    ObsidianRelationType.RESOLVES: "Resolves",
    ObsidianRelationType.DUPLICATES: "Duplicates",
    ObsidianRelationType.SUPPORTS: "Supports",
    ObsidianRelationType.EXTENDS: "Extends",
    ObsidianRelationType.CONTRADICTS: "Contradicts",
    ObsidianRelationType.CONTAINS: "Contains",
}
