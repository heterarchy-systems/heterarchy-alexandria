"""SQLAlchemy repository for Obsidian librarian workflow checkpoints."""

from __future__ import annotations

from typing import cast

from app.obsidian.domain.entities.obsidian_note import ObsidianLibrarianWorkflow
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianLibrarianWorkflowStatus,
)
from app.obsidian.domain.repositories.obsidian_workflow_repository import (
    IObsidianWorkflowRepository,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianLibrarianWorkflowORM,
)
from app.shared.types.extra_types import JSONObject
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyObsidianWorkflowRepository(IObsidianWorkflowRepository):
    """Persist Obsidian librarian workflow checkpoints through SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_workflow(self, workflow: ObsidianLibrarianWorkflow) -> None:
        """Persist one workflow checkpoint.

        Args:
            workflow: Workflow checkpoint entity.
        """
        model = await self._session.get(
            ObsidianLibrarianWorkflowORM, workflow.thread_id
        )
        if model is None:
            model = ObsidianLibrarianWorkflowORM(thread_id=workflow.thread_id)
            self._session.add(model)
        model.status = workflow.status.value
        model.query = workflow.query
        model.active_note_path = workflow.active_note_path
        model.project = workflow.project
        model.provider_id = workflow.provider_id
        model.profile_id = workflow.profile_id
        model.delegate_requested = workflow.delegate_requested
        model.state_json = workflow.state
        model.created_at = workflow.created_at
        model.updated_at = workflow.updated_at
        await self._session.flush()

    async def get_workflow(self, thread_id: str) -> ObsidianLibrarianWorkflow | None:
        """Read one workflow checkpoint by thread id.

        Args:
            thread_id: Workflow thread id.

        Returns:
            Workflow when found.
        """
        model = await self._session.get(ObsidianLibrarianWorkflowORM, thread_id)
        return None if model is None else _workflow_from_model(model)


def _workflow_from_model(
    model: ObsidianLibrarianWorkflowORM,
) -> ObsidianLibrarianWorkflow:
    return ObsidianLibrarianWorkflow(
        thread_id=model.thread_id,
        status=ObsidianLibrarianWorkflowStatus(model.status),
        query=model.query,
        active_note_path=model.active_note_path,
        project=model.project,
        provider_id=model.provider_id,
        profile_id=model.profile_id,
        delegate_requested=model.delegate_requested,
        state=cast(JSONObject, model.state_json),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
