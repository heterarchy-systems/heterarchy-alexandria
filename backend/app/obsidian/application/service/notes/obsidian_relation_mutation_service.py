"""Canonical source-frontmatter mutation for Obsidian graph relations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.obsidian.application.graph.relations.obsidian_graph_relation_targets import (
    _relation_targets,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianNoteWriteResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianFrontmatterMode,
    ObsidianRelationType,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianWriteConflictError,
)
from app.shared.exceptions.obsidian_relation_exceptions import (
    ObsidianRelateInvalidRelationError,
    ObsidianRelateSelfEdgeError,
)
from app.shared.types.extra_types import JSONValue

if TYPE_CHECKING:
    from app.obsidian.application.service.obsidian_service import ObsidianService


class ObsidianRelationMutationService:
    """Own one typed relation mutation shared by high-level write composites."""

    def __init__(self, obsidian_service: ObsidianService) -> None:
        """Create the relation mutation owner over canonical note writes."""
        self._obsidian_service = obsidian_service

    async def relate(
        self,
        *,
        source: ObsidianNote,
        target: ObsidianNote,
        relation: ObsidianRelationType,
        expected_source_hash: str | None = None,
        operation_source: str = "relate",
    ) -> ObsidianNoteWriteResult:
        """Persist one source-to-target relationship through the note CAS gateway.

        Markdown frontmatter remains the relationship authority. The existing note
        write gateway renders the managed wikilink section and updates the indexed
        edge cache; graph projection is rebuilt by the owning composite.
        """
        if source.note_id == target.note_id:
            raise ObsidianRelateSelfEdgeError(source.note_id)
        if (
            expected_source_hash is not None
            and source.content_hash != expected_source_hash
        ):
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: expected source content hash does not match "
                f"the current note: {source.relative_path}"
            )
        field_name = relation_field(relation)
        values = relation_values(source.frontmatter.get(field_name))
        if not relation_present(source, target, relation):
            values.append(
                {
                    "id": target.note_id,
                    "path": target.relative_path,
                    "relation": relation.value,
                }
            )
        payload = ObsidianSaveNote(
            title=source.title,
            body=source.body.removeprefix("\n"),
            alexandria_type=source.alexandria_type,
            note_id=source.note_id,
            relative_path=source.relative_path,
            tags=source.tags,
            status=source.status,
            project=source.project,
            source=source.source or operation_source,
            frontmatter={field_name: values},
            expected_content_hash=source.content_hash,
        )
        return await self._obsidian_service.write_note(
            ObsidianWriteNote(
                note=payload,
                write_mode=ObsidianWriteMode.UPDATE,
                match_by=ObsidianWriteMatchBy.PATH,
                frontmatter_mode=ObsidianFrontmatterMode.MERGE,
            )
        )


def relation_field(relation: ObsidianRelationType) -> str:
    """Return the canonical frontmatter field for a relation kind."""
    if relation is ObsidianRelationType.CITES:
        return "source_ref_links"
    if relation is ObsidianRelationType.WIKILINK:
        raise ObsidianRelateInvalidRelationError(relation.value)
    return relation.value


def relation_values(value: JSONValue | None) -> list[JSONValue]:
    """Normalize one frontmatter relation field without changing source authority."""
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def relation_present(
    source: ObsidianNote,
    target: ObsidianNote,
    relation: ObsidianRelationType,
) -> bool:
    """Return whether source already carries the exact directed relation."""
    field_name = relation_field(relation)
    for item in _relation_targets(source.frontmatter.get(field_name), field_name):
        target_id = item.note_id
        target_path = item.path
        item_relation = item.relation
        if (target_id == target.note_id or target_path == target.relative_path) and (
            item_relation is None or item_relation is relation
        ):
            return True
    return False
