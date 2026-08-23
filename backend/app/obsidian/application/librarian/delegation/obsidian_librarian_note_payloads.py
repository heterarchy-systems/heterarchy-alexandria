"""Approved note commands, transcript rendering, and source-ref mapping."""

from __future__ import annotations

from app.librarian.domain.entities.source_ref import SourceRef
from app.librarian.domain.event_enum.source_ref_enums import SourceRefType
from app.obsidian.application.graph.relations.obsidian_graph_relation_targets import (
    source_refs_from_json,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianLibrarianWorkflow
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
)
from app.shared.types.extra_types import JSONObject


def _save_note_command(
    workflow: ObsidianLibrarianWorkflow,
    title: str,
    body: str,
    alexandria_type: AlexandriaNoteType,
    note_id: str | None,
    relation_field: str,
    refs: list[JSONObject],
) -> ObsidianSaveNote:
    """Build an Obsidian save command for approved workflow writes.

    Args:
        workflow: Workflow used by this operation.
        title: Title used by this operation.
        body: Body used by this operation.
        alexandria_type: Alexandria type used by this operation.
        note_id: Identifier for note.
        relation_field: Relation field used by this operation.
        refs: Refs used by this operation.

    Returns:
        ObsidianSaveNote result produced by save note command.
    """
    frontmatter: JSONObject = {
        "workflow_thread_id": workflow.thread_id,
        "workflow_engine": "langgraph",
        "active_note_path": workflow.active_note_path,
        relation_field: refs,
    }
    if alexandria_type is AlexandriaNoteType.CONTEXT:
        frontmatter["scope"] = "PROJECT" if workflow.project is not None else "GLOBAL"
    return ObsidianSaveNote(
        title=title,
        body=body,
        alexandria_type=alexandria_type,
        note_id=note_id,
        tags=("alexandria", "librarian", "workflow"),
        project=workflow.project,
        source="obsidian-librarian-langgraph",
        frontmatter=frontmatter,
    )


def _transcript_body(workflow: ObsidianLibrarianWorkflow, response: JSONObject) -> str:
    """Render a transcript note body from a workflow response.

    Args:
        workflow: Workflow used by this operation.
        response: Response value being processed.

    Returns:
        str result produced by transcript body.
    """
    return f"""# Librarian Workflow

## Engine
LangGraph

## User
{workflow.query}

## Librarian
{response.get("answer_markdown") or ""}
"""


def _source_refs(response: JSONObject) -> tuple[SourceRef, ...]:
    """Convert Obsidian source refs into Hermes librarian source refs.

    Args:
        response: Response value being processed.

    Returns:
        tuple[SourceRef, ...] result produced by source refs.
    """
    refs: list[SourceRef] = []
    for item in source_refs_from_json(response.get("source_refs")):
        note_id = item.get("id")
        path = item.get("path")
        title = item.get("title")
        if not isinstance(note_id, str) or not isinstance(path, str):
            continue
        refs.append(
            SourceRef(
                source_type=SourceRefType.CONTEXT,
                source_id=note_id,
                title=title if isinstance(title, str) and title else path,
                detail_path=f"/obsidian/notes/{note_id}",
                preview=path,
            )
        )
    return tuple(refs)
