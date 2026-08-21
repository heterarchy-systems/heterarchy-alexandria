"""Approval action planning and interrupt payload policy."""

from __future__ import annotations

from app.obsidian.application.librarian.graph.obsidian_librarian_graph_contracts import (
    ObsidianLibrarianGraphState,
)
from app.obsidian.application.librarian.obsidian_librarian_state_access import (
    state_optional_string as _state_optional_string,
)
from app.shared.types.extra_types import JSONObject


def _pending_actions_from_state(
    state: ObsidianLibrarianGraphState,
) -> list[JSONObject]:
    """Plan workflow actions that require explicit user approval."""
    actions: list[JSONObject] = [
        _action("save_transcript", "Save transcript", "save_transcript"),
        _action("create_context_note", "Create context note", "create_context"),
        _action("create_skill_draft", "Create skill draft", "create_skill"),
    ]
    if _state_optional_string(state, "active_note_path") is not None:
        actions.insert(1, _action("add_graph_links", "Add graph links", "graph_links"))
    if bool(state.get("delegate_requested")):
        actions.append(
            _action("ask_oauth_librarian", "Ask GPT OAuth librarian", "delegate")
        )
    return actions


def _action(action_id: str, label: str, action_type: str) -> JSONObject:
    return {
        "id": action_id,
        "label": label,
        "type": action_type,
        "requires_approval": True,
    }
