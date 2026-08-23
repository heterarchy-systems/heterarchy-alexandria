"""Render managed Alexandria graph-link sections in Markdown bodies."""

from __future__ import annotations

import re

from app.obsidian.application.graph.relations.obsidian_graph_relation_contracts import (
    _FRONTMATTER_RELATIONS,
    _RELATION_HEADINGS,
    ALEXANDRIA_LINKS_END,
    ALEXANDRIA_LINKS_START,
)
from app.obsidian.application.graph.relations.obsidian_graph_relation_targets import (
    _relation_targets,
)
from app.shared.types.extra_types import JSONObject


def add_or_update_alexandria_links_section(body: str, frontmatter: JSONObject) -> str:
    """Render relation frontmatter as a managed body wikilink section.

    Args:
        body: Existing Markdown body.
        frontmatter: Note frontmatter containing relation fields.

    Returns:
        Body with the managed Alexandria Links section updated or appended.
    """
    section = _render_links_section(frontmatter)
    if not section:
        return body
    block = f"{ALEXANDRIA_LINKS_START}\n{section}\n{ALEXANDRIA_LINKS_END}"
    pattern = re.compile(
        rf"\n?{re.escape(ALEXANDRIA_LINKS_START)}.*?{re.escape(ALEXANDRIA_LINKS_END)}",
        re.DOTALL,
    )
    if pattern.search(body):
        return pattern.sub(f"\n\n{block}", body).strip() + "\n"
    return f"{body.rstrip()}\n\n{block}\n" if body.strip() else f"{block}\n"


def _render_links_section(frontmatter: JSONObject) -> str:
    """Render links section.

    Args:
        frontmatter: Frontmatter used by this operation.

    Returns:
        Rendered links section.
    """
    sections: list[str] = ["## Alexandria Links"]
    relation_lines = 0
    for field_name, relation in _FRONTMATTER_RELATIONS:
        targets = list(_relation_targets(frontmatter.get(field_name)))
        if not targets:
            continue
        lines: list[str] = []
        for target in targets:
            if target.path is None:
                continue
            link_target = target.path.strip().removesuffix(".md")
            relation_text = (target.relation or relation).value
            lines.append(f"- [[{link_target}]] — {relation_text}")
        if not lines:
            continue
        sections.extend(["", f"### {_RELATION_HEADINGS[relation]}", *lines])
        relation_lines += len(lines)
    return "\n".join(sections) if relation_lines else ""
