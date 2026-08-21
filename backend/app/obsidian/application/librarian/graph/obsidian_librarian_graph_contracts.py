"""State, result, and delegate contracts for Obsidian librarian LangGraph."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict

from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
)
from app.librarian.domain.types.hermes_collaboration_payload_types import (
    HermesLibrarianAskPayload,
)
from app.shared.types.extra_types import JSONObject


class ObsidianLibrarianDelegateService(ABC):
    """Narrow boundary for GPT/OAuth-backed librarian delegation."""

    @abstractmethod
    async def ask_librarian(
        self,
        command: HermesLibrarianAskCommand,
    ) -> HermesLibrarianAskPayload:
        """Ask the configured Hermes librarian delegate service.

        Args:
            command: Provider/profile-aware librarian command.

        Returns:
            Provider-backed librarian result payload.
        """


class ObsidianLibrarianGraphState(TypedDict, total=False):
    """Serializable LangGraph state for an Obsidian librarian workflow."""

    thread_id: str
    query: str
    active_note_path: str | None
    selection: str | None
    project: str | None
    preferred_alexandria_types: list[str]
    max_source_refs: int
    delegate_requested: bool
    provider_id: str | None
    profile_id: str | None
    response: JSONObject
    pending_actions: list[JSONObject]
    approved_actions: list[str]
    completed_actions: list[str]
    transcript_path: str | None
    workflow_status: str
    delegate_payload: JSONObject | None


class ObsidianLibrarianGraphResult(TypedDict, total=False):
    """Result returned by the LangGraph executor boundary."""

    state: JSONObject
    status: str
