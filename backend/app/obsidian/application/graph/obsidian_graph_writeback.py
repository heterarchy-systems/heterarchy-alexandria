"""Prepare approved librarian graph-link writebacks for Obsidian notes."""

from __future__ import annotations

from app.obsidian.application.graph.diagnostics.obsidian_graph_link_renderer import (
    add_or_update_alexandria_links_section,
)
from app.obsidian.application.graph.relations.obsidian_graph_relation_targets import (
    source_refs_from_json,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.types.extra_types import JSONObject


def graph_link_save_payload(
    note: ObsidianNote,
    response: JSONObject,
) -> ObsidianSaveNote:
    """Build a save command that applies librarian source refs to one note.

    Args:
        note: Authoritative active note loaded from Markdown.
        response: Librarian answer payload containing source refs.

    Returns:
        Save command preserving note identity and metadata.
    """
    refs = _graph_link_refs(
        source_refs_from_json(response.get("source_refs")),
        active_note_path=note.relative_path,
    )
    if not refs:
        raise ObsidianValidationError("no graph source refs to apply")
    frontmatter = dict(note.frontmatter)
    frontmatter["source_refs"] = _merged_relation_refs(
        source_refs_from_json(frontmatter.get("source_refs")),
        refs,
    )
    body = add_or_update_alexandria_links_section(note.body, frontmatter)
    return ObsidianSaveNote(
        title=note.title,
        body=body,
        alexandria_type=note.alexandria_type,
        note_id=note.note_id,
        relative_path=note.relative_path,
        tags=tuple(note.tags),
        status=note.status,
        project=note.project,
        source=note.source or "obsidian-librarian-langgraph",
        frontmatter=frontmatter,
    )


def _graph_link_refs(
    refs: list[JSONObject],
    active_note_path: str,
) -> list[JSONObject]:
    applied: list[JSONObject] = []
    for ref in refs:
        path = _string_ref(ref, "path")
        if path is None or path == active_note_path:
            continue
        payload: JSONObject = {
            "path": path,
            "relation": _string_ref(ref, "relation") or "cites",
        }
        note_id = _string_ref(ref, "id")
        if note_id is not None:
            payload["id"] = note_id
        applied.append(payload)
    return applied


def _merged_relation_refs(
    existing: list[JSONObject],
    additions: list[JSONObject],
) -> list[JSONObject]:
    merged: list[JSONObject] = []
    seen: set[tuple[str, str | None, str]] = set()
    for ref in [*existing, *additions]:
        path = _string_ref(ref, "path")
        if path is None:
            continue
        relation = _string_ref(ref, "relation") or "cites"
        note_id = _string_ref(ref, "id")
        key = (path, note_id, relation)
        if key in seen:
            continue
        seen.add(key)
        payload: JSONObject = {"path": path, "relation": relation}
        if note_id is not None:
            payload["id"] = note_id
        merged.append(payload)
    return merged


def _string_ref(ref: JSONObject, key: str) -> str | None:
    value = ref.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
