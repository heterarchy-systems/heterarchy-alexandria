"""Build deduplicated graph edge indexes from Obsidian notes."""

from __future__ import annotations

import hashlib

from app.obsidian.application.graph.diagnostics.obsidian_graph_path_policy import (
    _normalize_target_path,
    _wikilink_targets,
)
from app.obsidian.application.graph.relations.obsidian_graph_relation_contracts import (
    _FRONTMATTER_RELATIONS,
)
from app.obsidian.application.graph.relations.obsidian_graph_relation_targets import (
    _relation_targets,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianEdgeIndex
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.shared.types.extra_types import JSONObject


def relation_edges_from_note(
    note_id: str,
    relative_path: str,
    alexandria_root: str,
    frontmatter: JSONObject,
    body: str,
) -> list[ObsidianEdgeIndex]:
    """Parse frontmatter relation fields and body wikilinks into edge indexes.

    Args:
        note_id: Stable source note id.
        relative_path: Vault-relative source path.
        alexandria_root: Managed Alexandria root, or "." when the vault is root.
        frontmatter: Parsed Markdown frontmatter.
        body: Markdown body text.

    Returns:
        Deduplicated graph edges for repository indexing.
    """
    edges: list[ObsidianEdgeIndex] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for field_name, fallback_relation in _FRONTMATTER_RELATIONS:
        if field_name == "source_refs" and "source_ref_links" in frontmatter:
            continue
        for target in _relation_targets(
            frontmatter.get(field_name),
            field_name=field_name,
        ):
            relation = target.relation or fallback_relation
            target_path = _normalize_target_path(
                target.path,
                alexandria_root=alexandria_root,
            )
            if target_path is None:
                continue
            key = (
                target_path,
                relation.value,
                ObsidianEdgeSourceKind.FRONTMATTER.value,
                target.note_id,
            )
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                _edge(
                    source_note_id=note_id,
                    source_path=relative_path,
                    target_note_id=target.note_id,
                    target_path=target_path,
                    relation=relation,
                    source_kind=ObsidianEdgeSourceKind.FRONTMATTER,
                    confidence=1.0,
                )
            )
    for target_path in _wikilink_targets(
        body,
        relative_path=relative_path,
        alexandria_root=alexandria_root,
    ):
        if target_path == relative_path:
            continue
        key = (
            target_path,
            ObsidianRelationType.WIKILINK.value,
            ObsidianEdgeSourceKind.WIKILINK.value,
            None,
        )
        if key in seen:
            continue
        seen.add(key)
        edges.append(
            _edge(
                source_note_id=note_id,
                source_path=relative_path,
                target_note_id=None,
                target_path=target_path,
                relation=ObsidianRelationType.WIKILINK,
                source_kind=ObsidianEdgeSourceKind.WIKILINK,
                confidence=0.5,
            )
        )
    return edges


def _edge(
    source_note_id: str,
    source_path: str,
    target_note_id: str | None,
    target_path: str,
    relation: ObsidianRelationType,
    source_kind: ObsidianEdgeSourceKind,
    confidence: float,
) -> ObsidianEdgeIndex:
    edge_key = "|".join(
        [
            source_note_id,
            source_path,
            target_note_id or "",
            target_path,
            relation.value,
            source_kind.value,
        ]
    )
    return ObsidianEdgeIndex(
        edge_id=hashlib.sha256(edge_key.encode("utf-8")).hexdigest(),
        source_note_id=source_note_id,
        source_path=source_path,
        target_note_id=target_note_id,
        target_path=target_path,
        relation=relation,
        confidence=confidence,
        source_kind=source_kind,
    )
