"""Resumable Obsidian librarian workflow application service."""

from __future__ import annotations

from datetime import UTC, datetime

from app.obsidian.application.librarian.graph.obsidian_librarian_graph_contracts import (
    ObsidianLibrarianDelegateService,
)
from app.obsidian.application.librarian.graph.obsidian_librarian_langgraph import (
    ObsidianLibrarianLangGraphExecutor,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianAsk,
    ObsidianLibrarianWorkflowResume,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianLibrarianWorkflow
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianLibrarianWorkflowStatus,
)
from app.obsidian.domain.repositories.obsidian_workflow_repository import (
    IObsidianWorkflowRepository,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)
from app.shared.types.extra_types import JSONObject


class ObsidianLibrarianWorkflowService:
    """Run a LangGraph-powered librarian workflow with approval checkpoints."""

    def __init__(
        self,
        workflow_repository: IObsidianWorkflowRepository,
        graph_executor: ObsidianLibrarianLangGraphExecutor,
    ) -> None:
        """Initialize workflow orchestration dependencies.

        Args:
            workflow_repository: Durable workflow checkpoint repository.
            graph_executor: LangGraph node executor boundary.
        """
        self._workflow_repository = workflow_repository
        self._graph_executor = graph_executor

    @classmethod
    def from_services(
        cls,
        workflow_repository: IObsidianWorkflowRepository,
        obsidian_service: ObsidianService,
        delegate_service: ObsidianLibrarianDelegateService | None = None,
    ) -> ObsidianLibrarianWorkflowService:
        """Build the service from lower-level application services.

        Args:
            workflow_repository: Durable workflow checkpoint repository.
            obsidian_service: Obsidian vault application service.
            delegate_service: Optional GPT/OAuth-backed delegate service.

        Returns:
            Configured workflow service.
        """
        return cls(
            workflow_repository=workflow_repository,
            graph_executor=ObsidianLibrarianLangGraphExecutor(
                obsidian_service=obsidian_service,
                delegate_service=delegate_service,
            ),
        )

    async def start_workflow(
        self,
        ask: ObsidianLibrarianAsk,
    ) -> ObsidianLibrarianWorkflow:
        """Start and pause a LangGraph librarian workflow for approval.

        Args:
            ask: Obsidian librarian ask payload.

        Returns:
            Persisted waiting workflow checkpoint.
        """
        result = await self._graph_executor.start(ask)
        state = result["state"]
        workflow = _workflow_from_state(
            ask=ask,
            state=state,
            status=ObsidianLibrarianWorkflowStatus.WAITING_FOR_APPROVAL,
            created_at=datetime.now(UTC),
        )
        await self._workflow_repository.upsert_workflow(workflow)
        return workflow

    async def get_workflow(self, thread_id: str) -> ObsidianLibrarianWorkflow:
        """Read one workflow checkpoint.

        Args:
            thread_id: Workflow thread id.

        Returns:
            Persisted workflow checkpoint.
        """
        workflow = await self._workflow_repository.get_workflow(thread_id)
        if workflow is None:
            raise ObsidianNotFoundError(f"Obsidian workflow not found: {thread_id}")
        return workflow

    async def resume_workflow(
        self,
        command: ObsidianLibrarianWorkflowResume,
    ) -> ObsidianLibrarianWorkflow:
        """Resume a LangGraph workflow with approved actions.

        Args:
            command: Resume command with approved action ids.

        Returns:
            Completed workflow checkpoint.
        """
        workflow = await self.get_workflow(command.thread_id)
        if workflow.status == ObsidianLibrarianWorkflowStatus.CANCELLED:
            raise ObsidianValidationError("workflow is cancelled")
        if workflow.status != ObsidianLibrarianWorkflowStatus.WAITING_FOR_APPROVAL:
            raise ObsidianValidationError("workflow is not waiting for approval")
        unknown_actions = set(command.approved_actions).difference(
            _pending_action_ids(workflow.state)
        )
        if unknown_actions:
            unknown = ", ".join(sorted(unknown_actions))
            raise ObsidianValidationError(f"unknown workflow action: {unknown}")
        result = await self._graph_executor.resume(workflow, command)
        state = result["state"]
        updated = _workflow_from_state(
            ask=_ask_from_workflow(workflow),
            state=state,
            status=ObsidianLibrarianWorkflowStatus.COMPLETED,
            created_at=workflow.created_at,
        )
        await self._workflow_repository.upsert_workflow(updated)
        return updated

    async def cancel_workflow(self, thread_id: str) -> ObsidianLibrarianWorkflow:
        """Cancel a waiting workflow without writing Obsidian notes.

        Args:
            thread_id: Workflow thread id.

        Returns:
            Cancelled workflow checkpoint.
        """
        workflow = await self.get_workflow(thread_id)
        updated = ObsidianLibrarianWorkflow(
            thread_id=workflow.thread_id,
            status=ObsidianLibrarianWorkflowStatus.CANCELLED,
            query=workflow.query,
            active_note_path=workflow.active_note_path,
            project=workflow.project,
            provider_id=workflow.provider_id,
            profile_id=workflow.profile_id,
            delegate_requested=workflow.delegate_requested,
            state=workflow.state,
            created_at=workflow.created_at,
            updated_at=datetime.now(UTC),
        )
        await self._workflow_repository.upsert_workflow(updated)
        return updated


def _workflow_from_state(
    ask: ObsidianLibrarianAsk,
    state: JSONObject,
    status: ObsidianLibrarianWorkflowStatus,
    created_at: datetime,
) -> ObsidianLibrarianWorkflow:
    return ObsidianLibrarianWorkflow(
        thread_id=_state_string(state, "thread_id"),
        status=status,
        query=ask.query,
        active_note_path=ask.active_note_path,
        project=ask.project,
        provider_id=ask.provider_id,
        profile_id=ask.profile_id,
        delegate_requested=ask.delegate_to_librarian,
        state=state,
        created_at=created_at,
        updated_at=datetime.now(UTC),
    )


def _ask_from_workflow(workflow: ObsidianLibrarianWorkflow) -> ObsidianLibrarianAsk:
    return ObsidianLibrarianAsk(
        query=workflow.query,
        active_note_path=workflow.active_note_path,
        project=workflow.project,
        delegate_to_librarian=workflow.delegate_requested,
        provider_id=workflow.provider_id,
        profile_id=workflow.profile_id,
    )


def _state_string(state: JSONObject, key: str) -> str:
    value = state.get(key)
    return value if isinstance(value, str) else ""


def _pending_action_ids(state: JSONObject) -> set[str]:
    value = state.get("pending_actions")
    if not isinstance(value, list):
        return set()
    ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        action_id = item.get("id")
        if isinstance(action_id, str):
            ids.add(action_id)
    return ids
