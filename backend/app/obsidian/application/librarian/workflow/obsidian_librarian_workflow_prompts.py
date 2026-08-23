"""Prompt builders for Obsidian librarian workflow delegation."""

from __future__ import annotations

from app.obsidian.application.graph.relations.obsidian_graph_relation_targets import (
    source_refs_from_json,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianLibrarianWorkflow
from app.shared.types.extra_types import JSONObject


def delegate_prompt(
    workflow: ObsidianLibrarianWorkflow,
    response: JSONObject,
) -> str:
    """Render the prompt sent to the approved GPT/OAuth librarian delegate.

    Args:
        workflow: Persisted workflow whose question and note context are delegated.
        response: Local Obsidian context packet and source references.

    Returns:
        Prompt text for the provider-backed librarian.
    """
    return "\n\n".join(
        [
            "Answer the user's question using the Obsidian context packet below.",
            f"Question: {workflow.query}",
            f"Active note: {workflow.active_note_path or 'none'}",
            _selection_line_from_response(response),
            "If retrieved sources are empty, do not claim that no related notes exist; explain what context was used and what verification is still needed.",
            "Return the final answer, risks, missing sources, and graph/memory follow-up actions.",
            str(response.get("answer_markdown") or ""),
        ]
    )


def delegate_brief(
    workflow: ObsidianLibrarianWorkflow,
    response: JSONObject,
) -> str:
    """Render a structured delegate brief for provider-backed librarian calls.

    Args:
        workflow: Persisted workflow whose question and note context are delegated.
        response: Local Obsidian context packet and source references.

    Returns:
        Structured brief text for the provider-backed librarian.
    """
    source_paths = [
        str(ref.get("path"))
        for ref in source_refs_from_json(response.get("source_refs"))
        if isinstance(ref.get("path"), str)
    ]
    return "\n".join(
        [
            "# Obsidian Librarian Answer Brief",
            "",
            "Use this packet to answer the user's question. Do not review a prewritten answer.",
            "If retrieved sources are empty, treat that as insufficient retrieval evidence, not proof that no related notes exist.",
            "",
            f"- query: {workflow.query}",
            f"- project: {workflow.project or 'default'}",
            f"- active_note_path: {workflow.active_note_path or 'none'}",
            f"- selection_status: {_selection_status_from_response(response)}",
            f"- source_paths: {', '.join(source_paths) if source_paths else 'none'}",
            "",
            _selection_block_from_response(response),
            "",
            str(response.get("answer_markdown") or ""),
        ]
    )


def _selection_status_from_response(response: JSONObject) -> str:
    """Execute selection status from response.

    Args:
        response: Response value being processed.

    Returns:
        str result produced by selection status from response.
    """
    return "ingested" if _selection_excerpt_from_response(response) else "none"


def _selection_line_from_response(response: JSONObject) -> str:
    """Execute selection line from response.

    Args:
        response: Response value being processed.

    Returns:
        str result produced by selection line from response.
    """
    selection = _selection_excerpt_from_response(response)
    if selection is None:
        return "Selection: none"
    return f"Selection provided:\n{selection}"


def _selection_block_from_response(response: JSONObject) -> str:
    """Execute selection block from response.

    Args:
        response: Response value being processed.

    Returns:
        str result produced by selection block from response.
    """
    selection = _selection_excerpt_from_response(response)
    if selection is None:
        return "## Selection\nnone"
    return f"## Selection\n{selection}"


def _selection_excerpt_from_response(response: JSONObject) -> str | None:
    """Execute selection excerpt from response.

    Args:
        response: Response value being processed.

    Returns:
        str | None result produced by selection excerpt from response.
    """
    context = response.get("input_context")
    if not isinstance(context, dict):
        return None
    selection = context.get("selection_excerpt")
    return selection if isinstance(selection, str) and selection.strip() else None
