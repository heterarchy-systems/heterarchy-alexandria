"""Focused LangGraph nodes for Obsidian librarian workflows."""

from __future__ import annotations

from app.obsidian.application.librarian.graph.obsidian_librarian_graph_contracts import (
    ObsidianLibrarianGraphState,
)
from app.obsidian.application.librarian.graph.obsidian_librarian_graph_state_codec import (
    _ask_from_state as ask_from_state,
)
from app.obsidian.application.librarian.obsidian_librarian_state_access import (
    state_string,
)
from app.obsidian.application.librarian.workflow.obsidian_librarian_action_executor import (
    ObsidianLibrarianActionExecutor,
)
from app.obsidian.application.librarian.workflow.obsidian_librarian_approval_policy import (
    _pending_actions_from_state as pending_actions_from_state,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianAsk,
)


class ObsidianLibrarianGraphNodes:
    """Own workflow node behavior independently from graph runtime wiring."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        action_executor: ObsidianLibrarianActionExecutor,
    ) -> None:
        """Initialize graph node dependencies.

        Args:
            obsidian_service: Local Obsidian-aware librarian service.
            action_executor: Approved workflow action executor.
        """
        self._obsidian_service = obsidian_service
        self._action_executor = action_executor

    async def collect_context(
        self,
        state: ObsidianLibrarianGraphState,
    ) -> ObsidianLibrarianGraphState:
        """Collect librarian graph context.

        Args:
            state: Current workflow state.

        Returns:
            Graph state populated with collected librarian context.
        """
        ask = ask_from_state(state)
        response = await self._obsidian_service.ask_librarian(
            ObsidianLibrarianAsk(
                query=ask.query,
                active_note_path=ask.active_note_path,
                selection=ask.selection,
                project=ask.project,
                preferred_alexandria_types=ask.preferred_alexandria_types,
                max_source_refs=ask.max_source_refs,
                save_transcript=False,
                delegate_to_librarian=ask.delegate_to_librarian,
                provider_id=ask.provider_id,
                profile_id=ask.profile_id,
            )
        )
        response["conversation_id"] = state_string(state, "thread_id")
        return {"response": response, "workflow_status": "context_collected"}

    async def plan_actions(
        self,
        state: ObsidianLibrarianGraphState,
    ) -> ObsidianLibrarianGraphState:
        """Plan librarian graph actions.

        Args:
            state: Current workflow state.

        Returns:
            Graph state populated with planned librarian actions.
        """
        pending_actions = pending_actions_from_state(state)
        return {
            "pending_actions": pending_actions,
            "approved_actions": [],
            "completed_actions": [],
            "transcript_path": None,
            "workflow_status": "approval_required",
        }

    async def execute_approved_actions(
        self,
        state: ObsidianLibrarianGraphState,
    ) -> ObsidianLibrarianGraphState:
        """Execute approved librarian graph actions.

        Args:
            state: Current workflow state.

        Returns:
            Graph state after approved librarian actions execute.
        """
        return await self._action_executor.execute(state)

    async def finalize(
        self,
        state: ObsidianLibrarianGraphState,
    ) -> ObsidianLibrarianGraphState:
        """Finalize the librarian graph workflow state.

        Args:
            state: Current workflow state.

        Returns:
            Finalized librarian graph state.
        """
        return {"workflow_status": "completed"}
