"""Stateless LangGraph executor for durable Obsidian librarian workflows."""

from __future__ import annotations

from typing import cast

from app.obsidian.application.librarian.graph.obsidian_librarian_graph_contracts import (
    ObsidianLibrarianDelegateService,
    ObsidianLibrarianGraphResult,
    ObsidianLibrarianGraphState,
)
from app.obsidian.application.librarian.graph.obsidian_librarian_graph_nodes import (
    ObsidianLibrarianGraphNodes,
)
from app.obsidian.application.librarian.graph.obsidian_librarian_graph_state_codec import (
    _initial_graph_state as initial_graph_state,
    _result_from_graph_output as result_from_graph_output,
)
from app.obsidian.application.librarian.workflow.obsidian_librarian_action_executor import (
    ObsidianLibrarianActionExecutor,
)
from app.obsidian.application.notes.obsidian_note_templates import conversation_id
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianAsk,
    ObsidianLibrarianWorkflowResume,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianLibrarianWorkflow
from langgraph.graph import END, START, StateGraph


class ObsidianLibrarianLangGraphExecutor:
    """Execute two stateless graph phases around a PostgreSQL approval row.

    The workflow repository is the only durable checkpoint. The planning phase ends
    before any side effect and stores its complete JSON state. The execution phase
    reconstructs that state after approval and runs approved actions to completion.
    """

    def __init__(
        self,
        obsidian_service: ObsidianService,
        delegate_service: ObsidianLibrarianDelegateService | None = None,
    ) -> None:
        """Initialize and compile the two graph phases once.

        Args:
            obsidian_service: Local Obsidian-aware librarian service.
            delegate_service: Optional GPT/OAuth-backed librarian delegate.
        """
        action_executor = ObsidianLibrarianActionExecutor(
            obsidian_service=obsidian_service,
            delegate_service=delegate_service,
        )
        self._nodes = ObsidianLibrarianGraphNodes(
            obsidian_service=obsidian_service,
            action_executor=action_executor,
        )
        self._planning_graph = self._build_planning_graph().compile()
        self._execution_graph = self._build_execution_graph().compile()

    async def start(self, ask: ObsidianLibrarianAsk) -> ObsidianLibrarianGraphResult:
        """Run context collection and action planning to a durable approval state.

        Args:
            ask: Initial librarian ask command.

        Returns:
            Complete JSON state ready to persist as waiting for approval.
        """
        initial_state = initial_graph_state(
            thread_id=conversation_id(),
            ask=ask,
        )
        result = await self._planning_graph.ainvoke(initial_state)
        state = cast(ObsidianLibrarianGraphState, result)
        state["workflow_status"] = "waiting_for_approval"
        return result_from_graph_output(state)

    async def resume(
        self,
        workflow: ObsidianLibrarianWorkflow,
        command: ObsidianLibrarianWorkflowResume,
    ) -> ObsidianLibrarianGraphResult:
        """Execute approved actions from the repository-persisted graph state.

        Args:
            workflow: Persisted workflow checkpoint from PostgreSQL.
            command: Resume command with approved action ids.

        Returns:
            Completed graph state and status.
        """
        result = await self._execution_graph.ainvoke(_resume_state(workflow, command))
        return result_from_graph_output(cast(ObsidianLibrarianGraphState, result))

    def _build_planning_graph(self) -> StateGraph:
        # LangGraph accepts TypedDict state schemas at runtime, but its current
        # generic upper bound is not recognized by Pyrefly for this TypedDict.
        graph = StateGraph(ObsidianLibrarianGraphState)  # pyrefly: ignore [bad-specialization]
        graph.add_node("collect_context", self._nodes.collect_context)
        graph.add_node("plan_actions", self._nodes.plan_actions)
        graph.add_edge(START, "collect_context")
        graph.add_edge("collect_context", "plan_actions")
        graph.add_edge("plan_actions", END)
        return graph

    def _build_execution_graph(self) -> StateGraph:
        # Keep the same narrow third-party typing workaround as the planning graph.
        graph = StateGraph(ObsidianLibrarianGraphState)  # pyrefly: ignore [bad-specialization]
        graph.add_node("execute_approved_actions", self._nodes.execute_approved_actions)
        graph.add_node("finalize", self._nodes.finalize)
        graph.add_edge(START, "execute_approved_actions")
        graph.add_edge("execute_approved_actions", "finalize")
        graph.add_edge("finalize", END)
        return graph


def _resume_state(
    workflow: ObsidianLibrarianWorkflow,
    command: ObsidianLibrarianWorkflowResume,
) -> ObsidianLibrarianGraphState:
    """Reconstruct one internal graph state from the durable workflow row.

    Args:
        workflow: Persisted workflow entity.
        command: Validated approved action identifiers.

    Returns:
        Graph state for the post-approval execution phase.
    """
    state = cast(ObsidianLibrarianGraphState, dict(workflow.state))
    state["thread_id"] = workflow.thread_id
    state["query"] = workflow.query
    state["active_note_path"] = workflow.active_note_path
    state["project"] = workflow.project
    state["provider_id"] = workflow.provider_id
    state["profile_id"] = workflow.profile_id
    state["delegate_requested"] = workflow.delegate_requested
    state["approved_actions"] = list(command.approved_actions)
    state["workflow_status"] = "approval_resumed"
    return state
