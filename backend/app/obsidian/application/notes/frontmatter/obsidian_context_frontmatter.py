"""Stable public facade for Context-specific Obsidian frontmatter handling."""

from __future__ import annotations

from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
    context_identity_from_frontmatter,
    normalized_context_frontmatter,
    validate_scope_identity,
)
from app.obsidian.application.notes.lifecycle.obsidian_context_identity import (
    ObsidianContextIdentity,
    ObsidianContextProvenance,
)

__all__ = (
    "ObsidianContextIdentity",
    "ObsidianContextProvenance",
    "context_content_hash",
    "context_identity_from_frontmatter",
    "normalized_context_frontmatter",
    "validate_scope_identity",
)
