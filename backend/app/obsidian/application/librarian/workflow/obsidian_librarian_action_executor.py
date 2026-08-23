"""Execute approved actions for Obsidian librarian graph workflows."""

from __future__ import annotations

from typing import cast

from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
)
from app.obsidian.application.graph.relations.obsidian_graph_relation_targets import (
    source_refs_from_json,
)
from app.obsidian.application.librarian.delegation.obsidian_librarian_delegate_payloads import (
    _append_delegate_summary as append_delegate_summary,
    _delegate_status as delegate_status,
    _delegate_unavailable_payload as delegate_unavailable_payload,
)
from app.obsidian.application.librarian.delegation.obsidian_librarian_note_payloads import (
    _save_note_command as save_note_command,
    _source_refs as source_refs,
    _transcript_body as transcript_body,
)
from app.obsidian.application.librarian.graph.obsidian_librarian_graph_contracts import (
    ObsidianLibrarianDelegateService,
    ObsidianLibrarianGraphState,
)
from app.obsidian.application.librarian.graph.obsidian_librarian_graph_state_codec import (
    _pending_action_ids as pending_action_ids,
    _workflow_snapshot_from_state as workflow_snapshot_from_state,
)
from app.obsidian.application.librarian.obsidian_librarian_state_access import (
    state_object,
    state_optional_string,
    state_string_list,
)
from app.obsidian.application.librarian.workflow.obsidian_librarian_workflow_prompts import (
    delegate_brief,
    delegate_prompt,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianLibrarianWorkflow,
    ObsidianNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.exceptions.librarian_exceptions import LibrarianResourceNotFoundError
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.types.extra_types import JSONObject


class ObsidianLibrarianActionExecutor:
    """Apply approved workflow actions through focused persistence and delegation."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        delegate_service: ObsidianLibrarianDelegateService | None = None,
    ) -> None:
        """Initialize action execution dependencies.

        Args:
            obsidian_service: Obsidian note and graph operation service.
            delegate_service: Optional GPT/OAuth-backed librarian delegate.
        """
        self._obsidian_service = obsidian_service
        self._delegate_service = delegate_service

    async def execute(
        self,
        state: ObsidianLibrarianGraphState,
    ) -> ObsidianLibrarianGraphState:
        """Execute the librarian action.

        Args:
            state: Current workflow state.

        Returns:
            Graph state after executing the current librarian action.
        """
        response = dict(state_object(state, "response"))
        completed_actions = list(state_string_list(state, "completed_actions"))
        transcript_path = state_optional_string(state, "transcript_path")
        approved = set(state_string_list(state, "approved_actions"))
        unknown_actions = approved.difference(pending_action_ids(state))
        if unknown_actions:
            unknown = ", ".join(sorted(unknown_actions))
            raise ObsidianValidationError(f"unknown workflow action: {unknown}")
        workflow = workflow_snapshot_from_state(state)
        if "save_transcript" in approved and transcript_path is None:
            note = await self._save_transcript(workflow, response)
            transcript_path = note.relative_path
            response["transcript_path"] = transcript_path
            completed_actions.append("save_transcript")
        if "create_context_note" in approved:
            note = await self._create_answer_note(workflow, response, "context")
            completed_actions.append(f"create_context_note:{note.relative_path}")
        if "create_skill_draft" in approved:
            note = await self._create_answer_note(workflow, response, "skill")
            completed_actions.append(f"create_skill_draft:{note.relative_path}")
        if "add_graph_links" in approved:
            note = await self._apply_graph_links(workflow, response)
            response["graph_links_path"] = note.relative_path
            completed_actions.append(f"add_graph_links:{note.relative_path}")
        delegate_payload: JSONObject | None = None
        if "ask_oauth_librarian" in approved:
            delegate_payload = await self._ask_gpt_oauth_librarian(workflow, response)
            status = delegate_status(delegate_payload, response)
            completed_actions.append(f"ask_oauth_librarian:{status}")
            response["delegate_status"] = status
            append_delegate_summary(response, delegate_payload)
        return {
            "response": response,
            "completed_actions": completed_actions,
            "transcript_path": transcript_path,
            "delegate_payload": delegate_payload,
            "workflow_status": "actions_executed",
        }

    async def _save_transcript(
        self,
        workflow: ObsidianLibrarianWorkflow,
        response: JSONObject,
    ) -> ObsidianNote:
        """Save transcript.

        Args:
            workflow: Workflow used by this operation.
            response: Response value being processed.

        Returns:
            ObsidianNote result produced by save transcript.
        """
        body = transcript_body(workflow, response)
        refs = source_refs_from_json(response.get("source_refs"))
        return await self._obsidian_service.save_note(
            save_note_command(
                workflow=workflow,
                title=f"Librarian Chat {workflow.thread_id}",
                body=body,
                alexandria_type=AlexandriaNoteType.LIBRARIAN_CHAT,
                note_id=workflow.thread_id,
                relation_field="source_refs",
                refs=refs,
            )
        )

    async def _create_answer_note(
        self,
        workflow: ObsidianLibrarianWorkflow,
        response: JSONObject,
        note_kind: str,
    ) -> ObsidianNote:
        """Create answer note.

        Args:
            workflow: Workflow used by this operation.
            response: Response value being processed.
            note_kind: Note kind used by this operation.

        Returns:
            Created answer note.
        """
        alexandria_type = (
            AlexandriaNoteType.SKILL
            if note_kind == "skill"
            else AlexandriaNoteType.CONTEXT
        )
        title = (
            "Alexandria Skill Draft"
            if note_kind == "skill"
            else "Alexandria Context Note"
        )
        return await self._obsidian_service.save_note(
            save_note_command(
                workflow=workflow,
                title=title,
                body=str(response.get("answer_markdown") or ""),
                alexandria_type=alexandria_type,
                note_id=None,
                relation_field="derived_from",
                refs=[
                    {
                        "id": workflow.thread_id,
                        "path": str(response.get("transcript_path") or ""),
                        "relation": "derived_from",
                    }
                ],
            )
        )

    async def _apply_graph_links(
        self,
        workflow: ObsidianLibrarianWorkflow,
        response: JSONObject,
    ) -> ObsidianNote:
        """Apply graph links.

        Args:
            workflow: Workflow used by this operation.
            response: Response value being processed.

        Returns:
            ObsidianNote result produced by apply graph links.
        """
        active_note_path = workflow.active_note_path
        if active_note_path is None:
            raise ObsidianValidationError("active note is required for graph links")
        return await self._obsidian_service.apply_librarian_graph_links(
            active_note_path=active_note_path,
            response=response,
        )

    async def _ask_gpt_oauth_librarian(
        self,
        workflow: ObsidianLibrarianWorkflow,
        response: JSONObject,
    ) -> JSONObject | None:
        """Execute ask gpt oauth librarian.

        Args:
            workflow: Workflow used by this operation.
            response: Response value being processed.

        Returns:
            JSONObject | None result produced by ask gpt oauth librarian.
        """
        if self._delegate_service is None:
            return None
        command = HermesLibrarianAskCommand(
            prompt=delegate_prompt(workflow, response),
            agent_name="obsidian-librarian",
            project=workflow.project,
            task_summary=workflow.query,
            delegate_to_librarian=True,
            provider_id=workflow.provider_id,
            librarian_profile_id=workflow.profile_id,
            librarian_model=None,
            librarian_role_prompt=None,
            max_librarian_agents=1,
            routing_specialties=("obsidian", "graph", "oauth", "gpt"),
            source_refs=source_refs(response),
            librarian_brief=delegate_brief(workflow, response),
        )
        try:
            payload = await self._delegate_service.ask_librarian(command)
        except LibrarianResourceNotFoundError as error:
            return delegate_unavailable_payload(workflow, str(error))
        return cast(JSONObject, dict(payload))
