"""Obsidian librarian workflow checkpoint behavior tests."""

from __future__ import annotations

import os

from pathlib import Path

import anyio
import pytest
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
)
from app.librarian.domain.event_enum.collaboration_enums import (
    AcquisitionDecision,
    LibrarianDelegateKind,
    LibrarianDelegateStatus,
    LibrarianDelegationStatus,
)
from app.librarian.domain.types.hermes_collaboration_payload_types import (
    HermesLibrarianAskPayload,
)
from app.obsidian.application.librarian.graph.obsidian_librarian_graph_contracts import (
    ObsidianLibrarianDelegateService,
)
from app.obsidian.application.librarian.workflow.obsidian_librarian_workflow_service import (
    ObsidianLibrarianWorkflowService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianAsk,
    ObsidianLibrarianWorkflowResume,
    ObsidianSaveNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianLibrarianWorkflowStatus,
    ObsidianRelationType,
)
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.models.obsidian_index_models import ObsidianEdgeORM
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.obsidian.infrastructure.repositories.obsidian_workflow_repository import (
    SqlAlchemyObsidianWorkflowRepository,
)
from app.shared.exceptions.librarian_exceptions import LibrarianResourceNotFoundError
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.infrastructure.database import Database
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def _database_url(path: Path) -> str:
    del path
    return os.environ["DATABASE_URL"]


async def _services(
    tmp_path: Path,
    *,
    delegate_service: ObsidianLibrarianDelegateService | None = None,
) -> tuple[Database, AsyncSession, ObsidianService, ObsidianLibrarianWorkflowService]:
    database = Database(
        database_url=_database_url(tmp_path / "obsidian.db"), create_schema=True
    )
    await database.initialize()
    session = database.session()
    obsidian = ObsidianService(
        repository=SqlAlchemyObsidianIndexRepository(session=session),
        vault_path=str(tmp_path / "vault"),
        alexandria_root="Alexandria",
    )
    workflow = ObsidianLibrarianWorkflowService.from_services(
        workflow_repository=SqlAlchemyObsidianWorkflowRepository(session=session),
        obsidian_service=obsidian,
        delegate_service=delegate_service,
    )
    return database, session, obsidian, workflow


class FakeGptOauthLibrarian(ObsidianLibrarianDelegateService):
    """Fake GPT OAuth delegate service for behavior tests."""

    def __init__(self) -> None:
        self.commands: list[HermesLibrarianAskCommand] = []

    async def ask_librarian(
        self,
        command: HermesLibrarianAskCommand,
    ) -> HermesLibrarianAskPayload:
        """Return one completed fake delegate payload.

        Args:
            command: Captured delegate command.

        Returns:
            Completed delegate payload.
        """
        self.commands.append(command)
        return HermesLibrarianAskPayload(
            job_id="job-gpt-oauth",
            status=LibrarianDelegationStatus.COMPLETED,
            decision=AcquisitionDecision.DELEGATE_TO_LIBRARIAN,
            librarian_available=True,
            self_acquisition_allowed=True,
            recommendation="GPT OAuth librarian completed.",
            provider_id=command.provider_id,
            candidate_id=None,
            librarian_profile_id=command.librarian_profile_id,
            librarian_model="gpt-5.5",
            librarian_role_prompt=None,
            max_librarian_agents=1,
            route_preview=["Completed delegated librarians: 1"],
            selected_profiles=[command.librarian_profile_id or "request-default"],
            matched_specialties=["oauth"],
            quality_review_added=False,
            routing_reason="fake delegate",
            delegates=[
                {
                    "profile_id": command.librarian_profile_id or "request-default",
                    "provider_id": command.provider_id,
                    "status": LibrarianDelegateStatus.COMPLETED,
                    "delegate_type": LibrarianDelegateKind.SPECIALTY_REVIEW,
                    "summary": "GPT OAuth delegate reviewed the Obsidian answer.",
                    "matched_specialties": ["oauth"],
                }
            ],
        )


class MissingProfileGptOauthLibrarian(ObsidianLibrarianDelegateService):
    """Fake delegate service that mimics a missing requested GPT OAuth profile."""

    async def ask_librarian(
        self,
        command: HermesLibrarianAskCommand,
    ) -> HermesLibrarianAskPayload:
        """Raise the same not-found error as the profile router.

        Args:
            command: Delegate command that requested a missing profile.

        Returns:
            Never returns; the exception drives fallback behavior.
        """
        raise LibrarianResourceNotFoundError(
            f"Librarian profile not found: {command.librarian_profile_id}"
        )


def test_librarian_workflow_pauses_then_resumes_approved_writes(
    tmp_path: Path,
) -> None:
    """Workflow should checkpoint pending actions and write only approved notes."""

    async def scenario() -> tuple[str, list[str], str | None, bool]:
        database, session, obsidian, workflow_service = await _services(tmp_path)
        try:
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Storage Source",
                    body="# Storage Source\n\nObsidian is canonical storage.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_storage_source",
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            workflow = await workflow_service.start_workflow(
                ObsidianLibrarianAsk(
                    query="canonical storage",
                    project="heterarchy-alexandria",
                    delegate_to_librarian=True,
                    provider_id="codex-oauth",
                    profile_id="research-critic",
                )
            )
            before_related = await obsidian.search(
                query=workflow_query(), refresh=False
            )
            resumed = await workflow_service.resume_workflow(
                ObsidianLibrarianWorkflowResume(
                    thread_id=workflow.thread_id,
                    approved_actions=["save_transcript", "create_context_note"],
                )
            )
            transcript_path = resumed.state.get("transcript_path")
            transcript_exists = (
                isinstance(transcript_path, str)
                and (tmp_path / "vault" / transcript_path).exists()
            )
        finally:
            await session.close()
            await database.shutdown()
        return (
            resumed.status.value,
            list(resumed.state["completed_actions"]),
            transcript_path if isinstance(transcript_path, str) else None,
            len(before_related) == 1 and transcript_exists,
        )

    status, completed_actions, transcript_path, source_found = anyio.run(scenario)

    assert status == ObsidianLibrarianWorkflowStatus.COMPLETED.value
    assert completed_actions[0] == "save_transcript"
    assert completed_actions[1].startswith("create_context_note:")
    assert transcript_path is not None
    assert source_found is True


def test_librarian_workflow_applies_approved_graph_links_to_active_note(
    tmp_path: Path,
) -> None:
    """Approving graph links should mutate the active note and rebuild edge cache."""

    async def scenario() -> tuple[list[str], str, list[tuple[str, str, str]]]:
        database, session, obsidian, workflow_service = await _services(tmp_path)
        try:
            source = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Storage Source",
                    body="# Storage Source\n\nCanonical storage source.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_storage_source",
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            active = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Active Work Note",
                    body="# Active Work Note\n\nNeeds linked evidence.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_active_work_note",
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            workflow = await workflow_service.start_workflow(
                ObsidianLibrarianAsk(
                    query="canonical storage source",
                    active_note_path=active.relative_path,
                    project="heterarchy-alexandria",
                )
            )
            resumed = await workflow_service.resume_workflow(
                ObsidianLibrarianWorkflowResume(
                    thread_id=workflow.thread_id,
                    approved_actions=["add_graph_links"],
                )
            )
            updated = await obsidian.read_note_by_path(active.relative_path)
            related = await session.execute(
                select(ObsidianEdgeORM).where(
                    ObsidianEdgeORM.source_note_id == active.note_id
                )
            )
        finally:
            await session.close()
            await database.shutdown()
        return (
            list(resumed.state["completed_actions"]),
            updated.body,
            [
                (item.target_note_id or "", item.relation, "outgoing")
                for item in related.scalars().all()
                if item.target_note_id == source.note_id
            ],
        )

    completed_actions, body, related = anyio.run(scenario)

    assert completed_actions == [
        "add_graph_links:Alexandria/Contexts/Projects/Active Work Note.md"
    ]
    assert "[[Alexandria/Contexts/Projects/Storage Source]] — cites" in body
    assert set(related) == {
        ("ctx_storage_source", ObsidianRelationType.CITES.value, "outgoing"),
        ("ctx_storage_source", ObsidianRelationType.WIKILINK.value, "outgoing"),
    }


def test_librarian_workflow_runs_gpt_oauth_delegate_when_approved(
    tmp_path: Path,
) -> None:
    """Approving OAuth delegation should call the GPT/OAuth librarian service."""

    async def scenario() -> tuple[list[str], str, str, int]:
        delegate = FakeGptOauthLibrarian()
        database, session, _obsidian, workflow_service = await _services(
            tmp_path,
            delegate_service=delegate,
        )
        try:
            workflow = await workflow_service.start_workflow(
                ObsidianLibrarianAsk(
                    query="delegate check",
                    delegate_to_librarian=True,
                    provider_id="codex-oauth",
                    profile_id="research-critic",
                )
            )
            resumed = await workflow_service.resume_workflow(
                ObsidianLibrarianWorkflowResume(
                    thread_id=workflow.thread_id,
                    approved_actions=["ask_oauth_librarian"],
                )
            )
        finally:
            await session.close()
            await database.shutdown()
        response = resumed.state["response"]
        assert isinstance(response, dict)
        return (
            list(resumed.state["completed_actions"]),
            str(response["delegate_status"]),
            str(response["answer_markdown"]),
            len(delegate.commands),
        )

    completed, delegate_status, answer, command_count = anyio.run(scenario)

    assert completed == ["ask_oauth_librarian:COMPLETED"]
    assert delegate_status == "COMPLETED"
    assert "## GPT OAuth Librarian" in answer
    assert command_count == 1


def test_librarian_workflow_keeps_local_result_when_gpt_profile_is_missing(
    tmp_path: Path,
) -> None:
    """Missing GPT OAuth profile should become guidance-only, not a failed workflow."""

    async def scenario() -> tuple[str, list[str]]:
        database, session, _obsidian, workflow_service = await _services(
            tmp_path,
            delegate_service=MissingProfileGptOauthLibrarian(),
        )
        try:
            workflow = await workflow_service.start_workflow(
                ObsidianLibrarianAsk(
                    query="delegate check",
                    delegate_to_librarian=True,
                    provider_id="codex-oauth",
                    profile_id="missing-profile",
                )
            )
            resumed = await workflow_service.resume_workflow(
                ObsidianLibrarianWorkflowResume(
                    thread_id=workflow.thread_id,
                    approved_actions=["ask_oauth_librarian"],
                )
            )
        finally:
            await session.close()
            await database.shutdown()
        return str(resumed.state["response"]["delegate_status"]), list(
            resumed.state["completed_actions"]
        )

    status, completed = anyio.run(scenario)

    assert status == "GUIDANCE_ONLY"
    assert completed == ["ask_oauth_librarian:GUIDANCE_ONLY"]


def test_librarian_workflow_resumes_after_service_recreation(
    tmp_path: Path,
) -> None:
    """PostgreSQL-compatible workflow rows should survive service recreation."""

    async def scenario() -> tuple[str, list[str]]:
        database, session, _obsidian, workflow_service = await _services(tmp_path)
        try:
            workflow = await workflow_service.start_workflow(
                ObsidianLibrarianAsk(query="persistent approval")
            )
            await session.commit()
            await session.close()
            session = database.session()
            obsidian = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
            )
            restarted = ObsidianLibrarianWorkflowService.from_services(
                workflow_repository=SqlAlchemyObsidianWorkflowRepository(
                    session=session
                ),
                obsidian_service=obsidian,
            )
            resumed = await restarted.resume_workflow(
                ObsidianLibrarianWorkflowResume(
                    thread_id=workflow.thread_id,
                    approved_actions=["save_transcript"],
                )
            )
        finally:
            await session.close()
            await database.shutdown()
        return resumed.status.value, list(resumed.state["completed_actions"])

    status, completed_actions = anyio.run(scenario)

    assert status == ObsidianLibrarianWorkflowStatus.COMPLETED.value
    assert completed_actions == ["save_transcript"]


def test_librarian_workflow_rejects_unknown_or_repeated_resume(
    tmp_path: Path,
) -> None:
    """Workflow resume should only accept pending actions once."""

    async def scenario() -> tuple[str, str]:
        database, session, _obsidian, workflow_service = await _services(tmp_path)
        try:
            workflow = await workflow_service.start_workflow(
                ObsidianLibrarianAsk(query="approval check")
            )
            with pytest.raises(ObsidianValidationError) as unknown_error:
                await workflow_service.resume_workflow(
                    ObsidianLibrarianWorkflowResume(
                        thread_id=workflow.thread_id,
                        approved_actions=["not_a_pending_action"],
                    )
                )
            await workflow_service.resume_workflow(
                ObsidianLibrarianWorkflowResume(thread_id=workflow.thread_id)
            )
            with pytest.raises(ObsidianValidationError) as repeated_error:
                await workflow_service.resume_workflow(
                    ObsidianLibrarianWorkflowResume(thread_id=workflow.thread_id)
                )
        finally:
            await session.close()
            await database.shutdown()
        return str(unknown_error.value), str(repeated_error.value)

    unknown_message, repeated_message = anyio.run(scenario)

    assert "unknown workflow action" in unknown_message
    assert repeated_message == "workflow is not waiting for approval"


def workflow_query():
    from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSearchQuery

    return ObsidianSearchQuery(query="canonical storage", limit=3)
