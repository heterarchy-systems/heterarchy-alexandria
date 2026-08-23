"""Durable skill-acquisition service behavior tests."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import AuthType, ProviderType
from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.librarian.application.skill_acquisition.skill_acquisition_service import (
    SkillAcquisitionService,
)
from app.librarian.application.skill_artifacts.skill_artifact_publication_contracts import (
    PublishedSkillArtifact,
    SkillArtifactPublicationError,
)
from app.librarian.application.skill_artifacts.skill_artifact_publisher import (
    ObsidianSkillArtifactPublisher,
)
from app.librarian.application.skill_library.skill_library_search_contracts import (
    SkillCapabilityBrief,
)
from app.librarian.application.skill_library.skill_library_search_service import (
    SkillLibrarySearchService,
)
from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
    SkillAcquisitionEvidenceItem,
)
from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
    SkillAcquisitionJobStatus,
)
from app.librarian.domain.event_enum.skill_acquisition_enums import (
    ItemStatus,
    RiskLevel,
)
from app.librarian.domain.event_enum.skill_search_enums import SkillSearchDecision
from app.librarian.infrastructure.repositories.skill_acquisition_job_repository import (
    SqlAlchemySkillAcquisitionJobRepository,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote, ObsidianSearchHit
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)
from app.shared.exceptions.librarian_exceptions import LibrarianValidationError
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.infrastructure.database import Database

_NOW = datetime(2026, 5, 18, 17, 30, tzinfo=UTC)
_PROMPT_REFERENCE = "Prompts/Task Prompts/Librarian Operating Prompt v0.1.md"
_PROMPT_REFERENCE_HASH = hashlib.sha256(_PROMPT_REFERENCE.encode()).hexdigest()


class FakeProviderRepository(ILibrarianProviderRepository):
    """Provider repository fake for skill-acquisition service tests."""

    def __init__(self, providers: list[LibrarianProvider]) -> None:
        """Initialize fake providers."""
        self._providers = providers

    async def create(self, payload):  # type: ignore[no-untyped-def]
        """Unused in these tests."""
        raise NotImplementedError

    async def get(self, provider_id: str) -> LibrarianProvider | None:
        """Return one provider by id."""
        return next(
            (provider for provider in self._providers if provider.id == provider_id),
            None,
        )

    async def list_all(self) -> list[LibrarianProvider]:
        """Return all configured providers."""
        return list(self._providers)

    async def update(self, provider_id, payload):  # type: ignore[no-untyped-def]
        """Unused in these tests."""
        raise NotImplementedError

    async def delete(self, provider_id: str) -> None:
        """Unused in these tests."""
        raise NotImplementedError


class FakeArtifactPublisher:
    """Publisher fake for durable skill publication tests."""

    def __init__(self) -> None:
        """Initialize captured publish calls."""
        self.published: list[tuple[str, str]] = []

    async def publish_skill_artifact(
        self,
        *,
        job,  # type: ignore[no-untyped-def]
        artifact: SkillAcquisitionArtifact,
    ) -> PublishedSkillArtifact:
        """Return deterministic durable skill handles."""
        self.published.append((job.id, artifact.title))
        return PublishedSkillArtifact(
            skill_id="00000000-0000-4000-8000-000000000777",
            context_id=None,
            result_summary="Saved draft skill note: Alexandria/Skills/Drafts/HTTP.md",
            skill_note_path="Alexandria/Skills/Drafts/HTTP.md",
            stage=SkillAcquisitionJobStage.HANDOFF_READY,
            progress_summary="Saved, indexed, verified, and prepared handoff.",
            reindex_status="succeeded",
            verification_status="verified",
            handoff={
                "decision": "new_skill_acquired",
                "job": {
                    "id": job.id,
                    "status": "COMPLETED",
                    "stage": "HANDOFF_READY",
                },
                "progress_summary": "Saved, indexed, verified, and prepared handoff.",
                "skill": {
                    "id": "00000000-0000-4000-8000-000000000777",
                    "path": "Alexandria/Skills/Drafts/HTTP.md",
                    "status": "draft",
                },
                "evidence": [
                    {
                        "url_or_path": "https://example.com/http-fake",
                        "supports_claims": ["Hermes researched the capability."],
                    }
                ],
                "persistence": {
                    "saved": True,
                    "reindex_status": "succeeded",
                    "verified": True,
                },
                "current_task": {
                    "resume_summary": job.task_summary or job.prompt,
                    "next_steps": ["Use the draft HTTP fake skill."],
                    "stop_condition": "Stop when the caller can test the boundary.",
                },
            },
        )


class FakeSecretRepository(IProviderSecretRepository):
    """Provider secret fake that never exposes secrets in job payloads."""

    def __init__(self, secrets: dict[tuple[str, str], str]) -> None:
        """Initialize fake secrets."""
        self._secrets = secrets

    async def resolve(self, provider_id: str, key_name: str) -> str | None:
        """Resolve one fake secret."""
        return self._secrets.get((provider_id, key_name))

    async def set_secret(self, *, provider_id: str, key_name: str, value: str) -> None:
        """Unused in these tests."""
        raise NotImplementedError

    async def delete_for_provider(self, provider_id: str, key_name: str) -> None:
        """Unused in these tests."""
        raise NotImplementedError


def _provider(provider_id: str = "provider-1") -> LibrarianProvider:
    return LibrarianProvider(
        id=provider_id,
        name="OpenAI",
        provider_type=ProviderType.OPENAI,
        auth_type=AuthType.API_KEY,
        enabled=True,
        config={},
        created_at=_NOW,
        updated_at=_NOW,
    )


async def _service(
    path: Path,
    *,
    providers: list[LibrarianProvider],
    secrets: dict[tuple[str, str], str],
) -> tuple[Database, AsyncSession, SkillAcquisitionService]:
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    session = database.session()
    service = SkillAcquisitionService(
        repository=SqlAlchemySkillAcquisitionJobRepository(session=session),
        provider_repo=FakeProviderRepository(providers),
        secret_repo=FakeSecretRepository(secrets),
        now_provider=lambda: _NOW,
    )
    return database, session, service


async def _close(database: Database, session: AsyncSession) -> None:
    await session.commit()
    await session.close()
    await database.shutdown()


def test_skill_acquisition_job_returns_guidance_when_no_provider_exists(
    tmp_path: Path,
) -> None:
    """Missing providers should create a durable guidance-only job."""

    async def run_case() -> tuple[SkillAcquisitionJobStatus, bool, str | None]:
        database, session, service = await _service(
            tmp_path / "guidance.db", providers=[], secrets={}
        )
        try:
            job = await service.request_job(
                prompt="Need a Playwright skill",
                agent_name="Hermes",
                project="heterarchy-alexandria",
                task_summary="Browser automation gap",
            )
            persisted = await service.get_job(job.id)
            return persisted.status, persisted.result_available, persisted.error_message
        finally:
            await _close(database, session)

    status, result_available, error_message = anyio.run(run_case)

    assert status is SkillAcquisitionJobStatus.GUIDANCE_ONLY
    assert result_available is False
    assert error_message is None


def test_skill_acquisition_job_is_accepted_when_provider_can_execute(
    tmp_path: Path,
) -> None:
    """Executable providers should create a durable accepted job without secrets."""

    async def run_case() -> tuple[SkillAcquisitionJobStatus, str | None, str]:
        database, session, service = await _service(
            tmp_path / "accepted.db",
            providers=[_provider()],
            secrets={("provider-1", "api_key"): "SECRET-KEY"},
        )
        try:
            job = await service.request_job(
                prompt="Need a FastAPI skill",
                provider_id="provider-1",
                agent_name="Hermes",
            )
            serialized = f"{job}"
            return job.status, job.provider_id, serialized
        finally:
            await _close(database, session)

    status, provider_id, serialized = anyio.run(run_case)

    assert status is SkillAcquisitionJobStatus.ACCEPTED
    assert provider_id == "provider-1"
    assert "SECRET-KEY" not in serialized


def test_skill_acquisition_job_records_legacy_override_when_search_snapshot_missing(
    tmp_path: Path,
) -> None:
    """Direct job starts should preserve an explicit audit trail."""

    async def run_case() -> tuple[object, str | None, str | None, str | None]:
        database, session, service = await _service(
            tmp_path / "legacy-direct-start.db", providers=[], secrets={}
        )
        try:
            job = await service.request_job(
                prompt="Need a FastAPI streaming skill",
                agent_name="Hermes",
            )
            return (
                job.search_snapshot,
                job.acquisition_override_reason,
                job.prompt_reference,
                job.prompt_reference_hash,
            )
        finally:
            await _close(database, session)

    search_snapshot, override_reason, prompt_reference, prompt_reference_hash = (
        anyio.run(run_case)
    )

    assert search_snapshot is None
    assert override_reason is not None
    assert "search-first snapshot" in override_reason
    assert prompt_reference == _PROMPT_REFERENCE
    assert prompt_reference_hash == _PROMPT_REFERENCE_HASH


def test_skill_acquisition_job_records_search_snapshot_without_override(
    tmp_path: Path,
) -> None:
    """Search-first acquisition starts should persist the sufficiency snapshot."""

    async def run_case() -> tuple[object, str | None, str | None, str | None]:
        database, session, service = await _service(
            tmp_path / "search-snapshot.db", providers=[], secrets={}
        )
        snapshot = {
            "decision": "NOT_FOUND",
            "query": "browser automation skill",
            "gaps": ["No draft or active skill matched Playwright."],
            "candidates": [],
        }
        try:
            job = await service.request_job(
                prompt="Need a browser automation skill",
                agent_name="Hermes",
                search_snapshot=snapshot,
                acquisition_override_reason="should be ignored",
            )
            persisted = await service.get_job(job.id)
            return (
                persisted.search_snapshot,
                persisted.acquisition_override_reason,
                persisted.prompt_reference,
                persisted.prompt_reference_hash,
            )
        finally:
            await _close(database, session)

    search_snapshot, override_reason, prompt_reference, prompt_reference_hash = (
        anyio.run(run_case)
    )

    assert search_snapshot == {
        "decision": "NOT_FOUND",
        "query": "browser automation skill",
        "gaps": ["No draft or active skill matched Playwright."],
        "candidates": [],
    }
    assert override_reason is None
    assert prompt_reference == _PROMPT_REFERENCE
    assert prompt_reference_hash == _PROMPT_REFERENCE_HASH


def test_skill_acquisition_job_fails_without_provider_credentials(
    tmp_path: Path,
) -> None:
    """A selected provider without credentials should persist a sanitized failure."""

    async def run_case() -> tuple[SkillAcquisitionJobStatus, str | None]:
        database, session, service = await _service(
            tmp_path / "failed.db", providers=[_provider()], secrets={}
        )
        try:
            job = await service.request_job(
                prompt="Need a FastAPI skill",
                provider_id="provider-1",
                agent_name="Hermes",
            )
            return job.status, job.error_message
        finally:
            await _close(database, session)

    status, error_message = anyio.run(run_case)

    assert status is SkillAcquisitionJobStatus.FAILED
    assert error_message == "Provider credentials unavailable"


def test_skill_acquisition_job_rejects_search_unavailable_snapshot(
    tmp_path: Path,
) -> None:
    """Search-unavailable snapshots should block acquisition job creation."""

    async def run_case() -> str:
        database, session, service = await _service(
            tmp_path / "search-unavailable.db", providers=[], secrets={}
        )
        try:
            with pytest.raises(LibrarianValidationError) as raised:
                await service.request_job(
                    prompt="Need a browser automation skill",
                    agent_name="Hermes",
                    project="heterarchy-alexandria",
                    search_snapshot={
                        "decision": "SEARCH_UNAVAILABLE",
                        "handoff": {"decision": "skill_search_repair_required"},
                    },
                )
            return str(raised.value)
        finally:
            await _close(database, session)

    error_message = anyio.run(run_case)

    assert error_message == (
        "Skill acquisition blocked by search readiness: SEARCH_UNAVAILABLE"
    )


def test_skill_acquisition_job_rejects_sufficient_skill_snapshot(
    tmp_path: Path,
) -> None:
    """Sufficient reusable skills should block fallback acquisition jobs."""

    async def run_case() -> str:
        database, session, service = await _service(
            tmp_path / "sufficient-search-snapshot.db", providers=[], secrets={}
        )
        try:
            with pytest.raises(LibrarianValidationError) as raised:
                await service.request_job(
                    prompt="Need a browser automation skill",
                    agent_name="Hermes",
                    project="heterarchy-alexandria",
                    search_snapshot={
                        "decision": "FOUND_SUFFICIENT",
                        "candidates": [
                            {
                                "id": "skill_browser_automation",
                                "sufficiency_score": 10,
                            }
                        ],
                        "handoff": {
                            "decision": "existing_skill_found",
                            "skill": {"id": "skill_browser_automation"},
                        },
                    },
                )
            return str(raised.value)
        finally:
            await _close(database, session)

    error_message = anyio.run(run_case)

    assert error_message == (
        "Skill acquisition blocked because an existing skill is sufficient"
    )


def test_skill_acquisition_completion_rejects_active_publication_request(
    tmp_path: Path,
) -> None:
    """Acquired skills must remain draft/needs-review until human promotion."""

    async def run_case() -> str:
        database, session, service = await _service(
            tmp_path / "active-complete.db",
            providers=[],
            secrets={},
        )
        try:
            job = await service.request_job(
                prompt="Need a production deployment skill",
                agent_name="Hermes",
                project="heterarchy-alexandria",
            )
            with pytest.raises(LibrarianValidationError) as exc_info:
                await service.complete_with_skill_artifact(
                    job_id=job.id,
                    artifact=SkillAcquisitionArtifact(
                        title="Production deployment skill",
                        purpose="Deploy production services.",
                        content="Run deployment commands.",
                        activate=True,
                        status=ItemStatus.ACTIVE,
                    ),
                )
            return str(exc_info.value)
        finally:
            await _close(database, session)

    error_message = anyio.run(run_case)

    assert error_message == "Skill acquisition artifacts cannot be auto-activated"


def test_skill_acquisition_completion_rejects_failed_jobs(
    tmp_path: Path,
) -> None:
    """Failed jobs should not create a resume packet on completion."""

    async def run_case() -> str:
        database, session, service = await _service(
            tmp_path / "failed-complete.db",
            providers=[_provider()],
            secrets={},
        )
        try:
            job = await service.request_job(
                prompt="Need a deterministic HTTP mocking skill",
                provider_id="provider-1",
                agent_name="Hermes",
            )
            with pytest.raises(
                LibrarianValidationError,
                match="Skill acquisition job is not completable",
            ) as exc_info:
                await service.complete_with_skill_artifact(
                    job_id=job.id,
                    artifact=SkillAcquisitionArtifact(
                        title="HTTP boundary fake skill",
                        purpose="Build deterministic API boundary fakes.",
                        content="Prefer boundary fakes over internal mocks.",
                    ),
                )
            return str(exc_info.value)
        finally:
            await _close(database, session)

    error_message = anyio.run(run_case)

    assert error_message == "Skill acquisition job is not completable"


def test_skill_acquisition_completion_publishes_durable_skill_artifact(
    tmp_path: Path,
) -> None:
    """Completing with a publisher should save durable skill handles on the job."""

    async def run_case() -> tuple[
        str | None,
        str | None,
        str | None,
        str | None,
        SkillAcquisitionJobStage | None,
        str | None,
        str | None,
        object,
        object,
        str | None,
        str | None,
        str | None,
        list[tuple[str, str]],
    ]:
        database, session, service = await _service(
            tmp_path / "published-complete.db",
            providers=[],
            secrets={},
        )
        publisher = FakeArtifactPublisher()
        try:
            job = await service.request_job(
                prompt="Need a deterministic HTTP mocking skill",
                agent_name="Hermes",
                project="heterarchy-alexandria",
                search_snapshot={
                    "decision": "FOUND_PARTIAL",
                    "gaps": ["Existing notes do not cover HTTP fakes."],
                },
            )
            completed = await service.complete_with_skill_artifact(
                job_id=job.id,
                artifact=SkillAcquisitionArtifact(
                    title="HTTP boundary fake skill",
                    purpose="Build deterministic API boundary fakes.",
                    content="Prefer boundary fakes over internal collaborator mocks.",
                    evidence_urls=["https://example.com/http-fake"],
                    source_summary="Hermes researched the missing capability.",
                ),
                artifact_publisher=publisher,
            )
            return (
                completed.skill_id,
                completed.context_id,
                completed.result_summary,
                completed.skill_note_path,
                completed.stage,
                completed.reindex_status,
                completed.verification_status,
                completed.handoff,
                completed.search_snapshot,
                completed.acquisition_override_reason,
                completed.prompt_reference,
                completed.prompt_reference_hash,
                publisher.published,
            )
        finally:
            await _close(database, session)

    (
        skill_id,
        context_id,
        result_summary,
        skill_note_path,
        stage,
        reindex_status,
        verification_status,
        handoff,
        search_snapshot,
        acquisition_override_reason,
        prompt_reference,
        prompt_reference_hash,
        published,
    ) = anyio.run(run_case)

    assert {
        "skill_id": skill_id,
        "context_id": context_id,
        "result_summary": result_summary,
        "skill_note_path": skill_note_path,
        "stage": None if stage is None else stage.value,
        "reindex_status": reindex_status,
        "verification_status": verification_status,
        "handoff_decision": handoff["decision"],
        "search_snapshot": search_snapshot,
        "acquisition_override_reason": acquisition_override_reason,
        "prompt_reference": prompt_reference,
        "prompt_reference_hash": prompt_reference_hash,
    } == {
        "skill_id": "00000000-0000-4000-8000-000000000777",
        "context_id": None,
        "result_summary": "Saved draft skill note: Alexandria/Skills/Drafts/HTTP.md",
        "skill_note_path": "Alexandria/Skills/Drafts/HTTP.md",
        "stage": "HANDOFF_READY",
        "reindex_status": "succeeded",
        "verification_status": "verified",
        "handoff_decision": "new_skill_acquired",
        "search_snapshot": {
            "decision": "FOUND_PARTIAL",
            "gaps": ["Existing notes do not cover HTTP fakes."],
        },
        "acquisition_override_reason": None,
        "prompt_reference": _PROMPT_REFERENCE,
        "prompt_reference_hash": _PROMPT_REFERENCE_HASH,
    }
    assert published[0][1] == "HTTP boundary fake skill"
    assert {
        "progress_summary": handoff["progress_summary"],
        "skill_path": handoff["skill"]["path"],
        "evidence_count": len(handoff["evidence"]),
        "persistence_verified": handoff["persistence"]["verified"],
        "resume_summary": handoff["current_task"]["resume_summary"],
        "next_steps": handoff["current_task"]["next_steps"],
        "stop_condition": handoff["current_task"]["stop_condition"],
    } == {
        "progress_summary": "Saved, indexed, verified, and prepared handoff.",
        "skill_path": "Alexandria/Skills/Drafts/HTTP.md",
        "evidence_count": 1,
        "persistence_verified": True,
        "resume_summary": "Need a deterministic HTTP mocking skill",
        "next_steps": ["Use the draft HTTP fake skill."],
        "stop_condition": "Stop when the caller can test the boundary.",
    }


def test_skill_acquisition_completion_fails_closed_for_incomplete_handoff(
    tmp_path: Path,
) -> None:
    """Completion must not mark jobs complete with an incomplete resume handoff."""

    class IncompleteHandoffPublisher:
        async def publish_skill_artifact(
            self,
            *,
            job,  # type: ignore[no-untyped-def]
            artifact: SkillAcquisitionArtifact,
        ) -> PublishedSkillArtifact:
            _ = job
            _ = artifact
            return PublishedSkillArtifact(
                skill_id="00000000-0000-4000-8000-000000000777",
                result_summary="Saved draft skill note: Alexandria/Skills/Drafts/HTTP.md",
                skill_note_path="Alexandria/Skills/Drafts/HTTP.md",
                reindex_status="succeeded",
                verification_status="verified",
                handoff={
                    "decision": "new_skill_acquired",
                    "skill": {"id": "00000000-0000-4000-8000-000000000777"},
                },
            )

    async def run_case() -> tuple[
        SkillAcquisitionJobStatus,
        SkillAcquisitionJobStage | None,
        str | None,
        object,
    ]:
        database, session, service = await _service(
            tmp_path / "incomplete-handoff.db",
            providers=[],
            secrets={},
        )
        try:
            job = await service.request_job(
                prompt="Need a deterministic HTTP mocking skill",
                agent_name="Hermes",
                project="heterarchy-alexandria",
                search_snapshot={"decision": "NOT_FOUND"},
            )
            failed = await service.complete_with_skill_artifact(
                job_id=job.id,
                artifact=SkillAcquisitionArtifact(
                    title="HTTP boundary fake skill",
                    purpose="Build deterministic API boundary fakes.",
                    content="Prefer boundary fakes over internal collaborator mocks.",
                ),
                artifact_publisher=IncompleteHandoffPublisher(),
            )
            return failed.status, failed.stage, failed.error_message, failed.handoff
        finally:
            await _close(database, session)

    status, stage, error_message, handoff = anyio.run(run_case)

    assert {
        "status": status.value,
        "stage": None if stage is None else stage.value,
        "error_message": error_message,
        "handoff_decision": handoff["decision"],
        "repair_hint": handoff["repair"]["hint"],
    } == {
        "status": "FAILED",
        "stage": "FAILED",
        "error_message": "Skill acquisition handoff missing required fields: current_task, evidence, job, persistence, progress_summary",
        "handoff_decision": "skill_acquisition_repair_required",
        "repair_hint": "Skill acquisition handoff missing required fields: current_task, evidence, job, persistence, progress_summary",
    }


def test_skill_acquisition_completion_is_idempotent_for_completed_jobs(
    tmp_path: Path,
) -> None:
    """Repeating completion should return existing handles without republishing."""

    async def run_case() -> tuple[str | None, str | None, int]:
        database, session, service = await _service(
            tmp_path / "idempotent-complete.db",
            providers=[],
            secrets={},
        )
        publisher = FakeArtifactPublisher()
        try:
            job = await service.request_job(
                prompt="Need a deterministic HTTP mocking skill",
                agent_name="Hermes",
                project="heterarchy-alexandria",
                search_snapshot={
                    "decision": "FOUND_PARTIAL",
                    "gaps": ["Existing notes do not cover HTTP fakes."],
                },
            )
            artifact = SkillAcquisitionArtifact(
                title="HTTP boundary fake skill",
                purpose="Build deterministic API boundary fakes.",
                content="Prefer boundary fakes over internal collaborator mocks.",
                evidence_urls=["https://example.com/http-fake"],
                source_summary="Hermes researched the missing capability.",
            )
            await service.complete_with_skill_artifact(
                job_id=job.id,
                artifact=artifact,
                artifact_publisher=publisher,
            )
            second = await service.complete_with_skill_artifact(
                job_id=job.id,
                artifact=artifact,
                artifact_publisher=publisher,
            )
            return second.skill_id, second.skill_note_path, len(publisher.published)
        finally:
            await _close(database, session)

    skill_id, skill_note_path, publish_count = anyio.run(run_case)

    assert skill_id == "00000000-0000-4000-8000-000000000777"
    assert skill_note_path == "Alexandria/Skills/Drafts/HTTP.md"
    assert publish_count == 1


def test_skill_acquisition_completion_persists_repair_handoff_when_publisher_fails(
    tmp_path: Path,
) -> None:
    """Publisher failures should fail closed instead of leaving jobs ambiguous."""

    class FailingArtifactPublisher:
        async def publish_skill_artifact(
            self,
            *,
            job,  # type: ignore[no-untyped-def]
            artifact: SkillAcquisitionArtifact,
        ) -> PublishedSkillArtifact:
            _ = job
            _ = artifact
            raise LibrarianValidationError("Published skill artifact read-back failed")

    async def run_case() -> tuple[
        str,
        SkillAcquisitionJobStatus,
        SkillAcquisitionJobStage | None,
        str | None,
        str | None,
        object,
        object,
    ]:
        database, session, service = await _service(
            tmp_path / "publication-failed.db",
            providers=[],
            secrets={},
        )
        try:
            job = await service.request_job(
                prompt="Need a deterministic HTTP mocking skill",
                agent_name="Hermes",
                project="heterarchy-alexandria",
                search_snapshot={"decision": "NOT_FOUND"},
            )
            failed = await service.complete_with_skill_artifact(
                job_id=job.id,
                artifact=SkillAcquisitionArtifact(
                    title="HTTP boundary fake skill",
                    purpose="Build deterministic API boundary fakes.",
                    content="Prefer boundary fakes over internal collaborator mocks.",
                ),
                artifact_publisher=FailingArtifactPublisher(),
            )
            return (
                failed.id,
                failed.status,
                failed.stage,
                failed.error_message,
                failed.repair_hint,
                failed.handoff,
                failed.search_snapshot,
            )
        finally:
            await _close(database, session)

    job_id, status, stage, error_message, repair_hint, handoff, search_snapshot = (
        anyio.run(run_case)
    )

    assert {
        "status": status.value,
        "stage": None if stage is None else stage.value,
        "error_message": error_message,
        "repair_hint": repair_hint,
        "handoff_decision": handoff["decision"],
        "handoff_stage": handoff["job"]["stage"],
        "search_snapshot": search_snapshot,
    } == {
        "status": "FAILED",
        "stage": "SKILL_SAVED",
        "error_message": "Published skill artifact read-back failed",
        "repair_hint": "Published skill artifact read-back failed",
        "handoff_decision": "skill_acquisition_repair_required",
        "handoff_stage": "SKILL_SAVED",
        "search_snapshot": {"decision": "NOT_FOUND"},
    }
    assert handoff["repair"]["retry_key"] == job_id


def test_skill_acquisition_completion_preserves_saved_handles_when_verification_fails(
    tmp_path: Path,
) -> None:
    """Post-save failures should retain durable note handles for repair."""

    class VerificationFailingArtifactPublisher:
        async def publish_skill_artifact(
            self,
            *,
            job,  # type: ignore[no-untyped-def]
            artifact: SkillAcquisitionArtifact,
        ) -> PublishedSkillArtifact:
            _ = job
            _ = artifact
            raise SkillArtifactPublicationError(
                "Published skill artifact was not found by search",
                skill_id="00000000-0000-4000-8000-000000000777",
                skill_note_path="Alexandria/Skills/Drafts/HTTP.md",
                stage=SkillAcquisitionJobStage.SKILL_SAVED,
                verification_status="failed",
            )

    async def run_case() -> tuple[
        SkillAcquisitionJobStatus,
        SkillAcquisitionJobStage | None,
        str | None,
        str | None,
        str | None,
        str | None,
        object,
    ]:
        database, session, service = await _service(
            tmp_path / "verification-failed-handles.db",
            providers=[],
            secrets={},
        )
        try:
            job = await service.request_job(
                prompt="Need a deterministic HTTP mocking skill",
                agent_name="Hermes",
                project="heterarchy-alexandria",
                search_snapshot={"decision": "NOT_FOUND"},
            )
            failed = await service.complete_with_skill_artifact(
                job_id=job.id,
                artifact=SkillAcquisitionArtifact(
                    title="HTTP boundary fake skill",
                    purpose="Build deterministic API boundary fakes.",
                    content="Prefer boundary fakes over internal collaborator mocks.",
                ),
                artifact_publisher=VerificationFailingArtifactPublisher(),
            )
            return (
                failed.status,
                failed.stage,
                failed.skill_id,
                failed.skill_note_path,
                failed.verification_status,
                failed.repair_hint,
                failed.handoff,
            )
        finally:
            await _close(database, session)

    (
        status,
        stage,
        skill_id,
        skill_note_path,
        verification_status,
        repair_hint,
        handoff,
    ) = anyio.run(run_case)

    assert {
        "status": status.value,
        "stage": None if stage is None else stage.value,
        "skill_id": skill_id,
        "skill_note_path": skill_note_path,
        "verification_status": verification_status,
        "repair_hint": repair_hint,
        "handoff_decision": handoff["decision"],
        "handoff_saved_skill_id": handoff["saved_handles"]["skill_id"],
        "handoff_saved_path": handoff["saved_handles"]["skill_note_path"],
    } == {
        "status": "FAILED",
        "stage": "SKILL_SAVED",
        "skill_id": "00000000-0000-4000-8000-000000000777",
        "skill_note_path": "Alexandria/Skills/Drafts/HTTP.md",
        "verification_status": "failed",
        "repair_hint": "Published skill artifact was not found by search",
        "handoff_decision": "skill_acquisition_repair_required",
        "handoff_saved_skill_id": "00000000-0000-4000-8000-000000000777",
        "handoff_saved_path": "Alexandria/Skills/Drafts/HTTP.md",
    }


def test_skill_acquisition_completion_persists_sanitized_secret_guardrail_failure(
    tmp_path: Path,
) -> None:
    """Secret-like artifact bodies should fail closed with sanitized job state."""

    class SecretBlockingArtifactPublisher:
        async def publish_skill_artifact(
            self,
            *,
            job,  # type: ignore[no-untyped-def]
            artifact: SkillAcquisitionArtifact,
        ) -> PublishedSkillArtifact:
            _ = job
            _ = artifact
            raise ObsidianValidationError("high-risk secret content cannot be saved")

    async def run_case() -> tuple[
        SkillAcquisitionJobStatus,
        SkillAcquisitionJobStage | None,
        str | None,
        str | None,
        object,
    ]:
        database, session, service = await _service(
            tmp_path / "secret-guardrail.db",
            providers=[],
            secrets={},
        )
        try:
            job = await service.request_job(
                prompt="Need a secret handling skill",
                agent_name="Hermes",
                project="heterarchy-alexandria",
            )
            failed = await service.complete_with_skill_artifact(
                job_id=job.id,
                artifact=SkillAcquisitionArtifact(
                    title="Secret Handling",
                    purpose="Avoid storing secrets.",
                    content="Never persist raw credentials.",
                ),
                artifact_publisher=SecretBlockingArtifactPublisher(),
            )
            return (
                failed.status,
                failed.stage,
                failed.error_message,
                failed.repair_hint,
                failed.handoff,
            )
        finally:
            await _close(database, session)

    status, stage, error_message, repair_hint, handoff = anyio.run(run_case)

    assert {
        "status": status.value,
        "stage": None if stage is None else stage.value,
        "error_message": error_message,
        "repair_hint": repair_hint,
        "handoff_decision": handoff["decision"],
    } == {
        "status": "FAILED",
        "stage": "FAILED",
        "error_message": "high-risk secret content cannot be saved",
        "repair_hint": "high-risk secret content cannot be saved",
        "handoff_decision": "skill_acquisition_repair_required",
    }


def test_skill_acquisition_completion_records_artifact_without_context_write(
    tmp_path: Path,
) -> None:
    """Completing a guidance-only job should skip retired internal skill and context CRUD."""

    async def run_case() -> tuple[
        SkillAcquisitionJobStatus,
        bool,
        str | None,
        str | None,
        list[str],
    ]:
        database, session, service = await _service(
            tmp_path / "complete.db",
            providers=[],
            secrets={},
        )
        try:
            job = await service.request_job(
                prompt="Need a deterministic HTTP mocking skill",
                agent_name="Hermes",
                project="heterarchy-alexandria",
                task_summary="Replace brittle API tests.",
            )
            completed = await service.complete_with_skill_artifact(
                job_id=job.id,
                artifact=SkillAcquisitionArtifact(
                    title="HTTP boundary fake skill",
                    purpose="Build deterministic API boundary fakes.",
                    summary="Use fake HTTP boundaries instead of internals.",
                    content="Prefer boundary fakes over internal collaborator mocks.",
                    tags=["testing", "http"],
                    required_tools=["pytest"],
                    evidence_urls=[" https://example.com/http-fake "],
                    source_summary="Hermes researched the missing capability.",
                    next_steps=["Apply the skill to the failing route test."],
                ),
            )
            return (
                completed.status,
                completed.result_available,
                completed.skill_id,
                completed.context_id,
                completed.evidence_urls,
            )
        finally:
            await _close(database, session)

    status, result_available, skill_id, context_id, evidence_urls = anyio.run(run_case)

    assert status is SkillAcquisitionJobStatus.COMPLETED
    assert result_available is True
    assert skill_id is None
    assert context_id is None
    assert evidence_urls == ("https://example.com/http-fake",)


def _fake_skill_note(
    note_id: str,
    *,
    body: str = "",
    frontmatter: dict[str, object] | None = None,
):
    class Note:
        pass

    note = Note()
    note.note_id = note_id
    note.relative_path = "Alexandria/Skills/Drafts/HTTP Boundary Fake.md"
    note.body = body
    note.frontmatter = {} if frontmatter is None else dict(frontmatter)
    return note


def _obsidian_note_from_saved_payload(payload) -> ObsidianNote:  # type: ignore[no-untyped-def]
    return ObsidianNote(
        note_id=payload.note_id,
        relative_path=payload.relative_path
        or f"Alexandria/Skills/Drafts/{payload.title}.md",
        alexandria_type=AlexandriaNoteType.SKILL,
        title=payload.title,
        status=payload.status,
        tags=list(payload.tags),
        project=payload.project,
        source=payload.source,
        content_hash="hash",
        frontmatter=dict(payload.frontmatter),
        body=payload.body,
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=len(payload.body.encode("utf-8")),
        modified_at=_NOW,
        indexed_at=_NOW,
    )


def _publisher_job() -> SkillAcquisitionJob:
    return SkillAcquisitionJob(
        id="skill-acquisition-1",
        prompt="Need HTTP fakes",
        agent_name="Hermes",
        project="heterarchy-alexandria",
        task_summary="Replace brittle route tests.",
        status=SkillAcquisitionJobStatus.ACCEPTED,
        provider_id=None,
        librarian_profile_id=None,
        skill_id=None,
        context_id=None,
        result_summary=None,
        evidence_urls=[],
        error_message=None,
        created_at=_NOW,
        updated_at=_NOW,
        completed_at=None,
    )


def test_obsidian_skill_artifact_publisher_saves_draft_skill_note() -> None:
    """Obsidian publisher should save a deterministic draft skill note."""

    class FakeObsidianService:
        def __init__(self) -> None:
            self.payloads = []
            self.read_note_ids: list[str] = []
            self.search_queries = []

        async def save_note(self, payload):  # type: ignore[no-untyped-def]
            self.payloads.append(payload)
            return _fake_skill_note(
                payload.note_id,
                body=payload.body,
                frontmatter=payload.frontmatter,
            )

        async def read_note(self, note_id: str):  # type: ignore[no-untyped-def]
            self.read_note_ids.append(note_id)
            payload = self.payloads[0]
            return _fake_skill_note(
                note_id,
                body=payload.body,
                frontmatter=payload.frontmatter,
            )

        async def search(self, query, *, refresh: bool = True):  # type: ignore[no-untyped-def]
            self.search_queries.append((query, refresh))

            class Hit:
                pass

            hit = Hit()
            hit.note = _fake_skill_note(self.payloads[0].note_id)
            hit.excerpt = "HTTP Boundary Fake"
            hit.score = 1.0
            return [hit]

    async def run_case() -> tuple[
        str,
        str | None,
        str | None,
        object,
        list[str],
        list[tuple[object, bool]],
    ]:
        obsidian_service = FakeObsidianService()
        publisher = ObsidianSkillArtifactPublisher(obsidian_service)  # type: ignore[arg-type]
        result = await publisher.publish_skill_artifact(
            job=_publisher_job(),
            artifact=SkillAcquisitionArtifact(
                title="HTTP Boundary Fake",
                purpose="Build deterministic HTTP boundary fakes.",
                content="Use boundary fakes instead of internal mocks.",
                tags=["testing", "testing"],
                required_tools=["pytest"],
                evidence_urls=[" https://example.com/http "],
                source_summary="Primary source reviewed.",
                next_steps=["Apply to failing tests."],
            ),
        )
        return (
            result.skill_id,
            result.context_id,
            result.result_summary,
            obsidian_service.payloads[0],
            obsidian_service.read_note_ids,
            obsidian_service.search_queries,
        )

    skill_id, context_id, result_summary, payload, read_note_ids, search_queries = (
        anyio.run(run_case)
    )

    assert skill_id == "2d4ea19c-1041-5ea2-8897-af8d5d98cad3"
    assert context_id is None
    assert (
        result_summary
        == "Saved and verified draft skill note: Alexandria/Skills/Drafts/HTTP Boundary Fake.md"
    )
    assert payload.note_id == skill_id
    assert payload.alexandria_type.value == "skill"
    assert payload.status == "draft"
    assert payload.project == "heterarchy-alexandria"
    assert payload.source == "skill_acquisition"
    assert payload.tags == ("skill-acquisition", "testing")
    expected_sections = [
        "## 목적",
        "## 언제 사용해야 하는가",
        "## 언제 사용하지 말아야 하는가",
        "## 입력/사전조건",
        "## 단계별 절차 (Procedure)",
        "## 출력 계약",
        "## 실패 모드와 복구",
        "## 안전·권한·비밀정보 가드레일",
        "## 사용 예시",
        "## Evidence와 claim mapping",
        "## 현재 task에 적용하는 next steps",
        "## 버전/변경 이력",
    ]
    assert {
        "source_job_id": payload.frontmatter["source_job_id"],
        "risk_level": payload.frontmatter["risk_level"],
        "created_at": payload.frontmatter["created_at"],
        "when_not_to_use": payload.frontmatter["when_not_to_use"],
        "supersedes": payload.frontmatter["supersedes"],
    } == {
        "source_job_id": "skill-acquisition-1",
        "risk_level": "LOW",
        "created_at": _NOW.isoformat(),
        "when_not_to_use": [],
        "supersedes": [],
    }
    assert all(section in payload.body for section in expected_sections)
    assert "Use boundary fakes" in payload.body
    assert "https://example.com/http supports: Primary source reviewed." in payload.body
    assert read_note_ids == [skill_id]
    search_query, refresh = search_queries[0]
    assert search_query.query == "HTTP Boundary Fake"
    assert search_query.alexandria_type.value == "skill"
    assert search_query.project == "heterarchy-alexandria"
    assert refresh is True


def test_completed_skill_artifact_is_rediscovered_by_search_first_for_reuse() -> None:
    """A freshly published draft skill should satisfy the next reuse handoff."""

    class FakeObsidianService:
        def __init__(self) -> None:
            self.payloads = []

        async def save_note(self, payload):  # type: ignore[no-untyped-def]
            self.payloads.append(payload)
            return _fake_skill_note(
                payload.note_id,
                body=payload.body,
                frontmatter=payload.frontmatter,
            )

        async def read_note(self, note_id: str):  # type: ignore[no-untyped-def]
            payload = self.payloads[0]
            return _fake_skill_note(
                note_id,
                body=payload.body,
                frontmatter=payload.frontmatter,
            )

        async def search(self, query, *, refresh: bool = True):  # type: ignore[no-untyped-def]
            _ = query
            _ = refresh
            payload = self.payloads[0]
            return [
                ObsidianSearchHit(
                    note=_obsidian_note_from_saved_payload(payload),
                    excerpt="HTTP boundary fake pytest procedure",
                    score=4.0,
                )
            ]

    async def run_case():  # type: ignore[no-untyped-def]
        obsidian_service = FakeObsidianService()
        publisher = ObsidianSkillArtifactPublisher(obsidian_service)  # type: ignore[arg-type]
        published = await publisher.publish_skill_artifact(
            job=_publisher_job(),
            artifact=SkillAcquisitionArtifact(
                title="HTTP Boundary Fake",
                purpose="Build deterministic HTTP boundary fakes.",
                content="Use boundary fakes instead of internal mocks.",
                required_tools=["pytest"],
                evidence_urls=["https://example.com/http"],
                source_summary="Primary source reviewed.",
                next_steps=["Apply to failing tests."],
            ),
        )
        result = await SkillLibrarySearchService(obsidian_service).search_first(
            SkillCapabilityBrief(
                capability="HTTP boundary fake",
                task_goal="Replace brittle HTTP tests",
                project="heterarchy-alexandria",
                required_tools=["pytest"],
            )
        )
        return published, result

    published, result = anyio.run(run_case)

    assert result.decision is SkillSearchDecision.FOUND_PARTIAL
    assert result.handoff is not None
    assert result.handoff["decision"] == "existing_skill_found"
    assert result.handoff["skill"] == {
        "id": published.skill_id,
        "title": "HTTP Boundary Fake",
        "path": "Alexandria/Skills/Drafts/HTTP Boundary Fake.md",
        "status": "draft",
        "version": "1.0.0",
        "risk_level": "LOW",
        "required_tools": ["pytest"],
    }
    assert result.handoff["current_task"]["next_steps"] == [
        "Open and apply existing skill note: Alexandria/Skills/Drafts/HTTP Boundary Fake.md",
        "Do not start librarian acquisition for this capability unless reuse fails.",
    ]
    assert result.gaps == (
        "skill status is draft; human review is required before reuse",
    )


def test_obsidian_skill_artifact_publisher_requires_evidence_for_source_summary() -> (
    None
):
    """Externally sourced claims should not be saved without evidence handles."""

    async def run_case() -> str:
        publisher = ObsidianSkillArtifactPublisher(object())  # type: ignore[arg-type]
        with pytest.raises(LibrarianValidationError) as raised:
            await publisher.publish_skill_artifact(
                job=_publisher_job(),
                artifact=SkillAcquisitionArtifact(
                    title="HTTP Boundary Fake",
                    purpose="Build deterministic HTTP boundary fakes.",
                    content="Use boundary fakes instead of internal mocks.",
                    source_summary="Primary documentation confirms this procedure.",
                ),
            )
        return str(raised.value)

    error_message = anyio.run(run_case)

    assert (
        error_message == "Skill artifact source summary requires claim-linked evidence"
    )


def test_obsidian_skill_artifact_publisher_requires_claim_mapping_for_evidence() -> (
    None
):
    """Evidence URLs should be linked to a source-summary claim mapping."""

    async def run_case() -> str:
        publisher = ObsidianSkillArtifactPublisher(object())  # type: ignore[arg-type]
        with pytest.raises(LibrarianValidationError) as raised:
            await publisher.publish_skill_artifact(
                job=_publisher_job(),
                artifact=SkillAcquisitionArtifact(
                    title="HTTP Boundary Fake",
                    purpose="Build deterministic HTTP boundary fakes.",
                    content="Use boundary fakes instead of internal mocks.",
                    evidence_urls=["https://example.com/http"],
                ),
            )
        return str(raised.value)

    error_message = anyio.run(run_case)

    assert (
        error_message
        == "Skill artifact evidence requires a source summary claim mapping"
    )


def test_obsidian_skill_artifact_publisher_preserves_structured_evidence_items() -> (
    None
):
    """Evidence gate should preserve claim-linked source metadata."""

    class FakeObsidianService:
        def __init__(self) -> None:
            self.payloads = []

        async def save_note(self, payload):  # type: ignore[no-untyped-def]
            self.payloads.append(payload)
            return _fake_skill_note(
                payload.note_id,
                body=payload.body,
                frontmatter=payload.frontmatter,
            )

        async def read_note(self, note_id: str):  # type: ignore[no-untyped-def]
            payload = self.payloads[0]
            return _fake_skill_note(
                note_id,
                body=payload.body,
                frontmatter=payload.frontmatter,
            )

        async def search(self, query, *, refresh: bool = True):  # type: ignore[no-untyped-def]
            class Hit:
                pass

            hit = Hit()
            hit.note = _fake_skill_note(self.payloads[0].note_id)
            hit.excerpt = "Production Deployment Skill"
            hit.score = 1.0
            return [hit]

    async def run_case() -> tuple[object, dict[str, object]]:
        obsidian_service = FakeObsidianService()
        publisher = ObsidianSkillArtifactPublisher(obsidian_service)  # type: ignore[arg-type]
        result = await publisher.publish_skill_artifact(
            job=_publisher_job(),
            artifact=SkillAcquisitionArtifact(
                title="Production Deployment Skill",
                purpose="Deploy production services safely.",
                content="Review the release plan, run deployment, verify rollback.",
                risk_level=RiskLevel.HIGH,
                evidence_items=[
                    SkillAcquisitionEvidenceItem(
                        url_or_path="https://docs.example.com/deploy",
                        title="Deployment API",
                        source_kind="primary_docs",
                        publisher_or_repository="example/docs",
                        accessed_at="2026-07-17",
                        supports_claims=["deployment command semantics"],
                        freshness="current",
                        notes="official release documentation",
                    ),
                    SkillAcquisitionEvidenceItem(
                        url_or_path="https://status.example.net/rollback",
                        title="Rollback Runbook",
                        source_kind="runbook",
                        publisher_or_repository="ops/runbooks",
                        accessed_at="2026-07-17",
                        supports_claims=["rollback verification procedure"],
                        freshness="reviewed",
                        notes="independent operational runbook",
                    ),
                ],
            ),
        )
        return obsidian_service.payloads[0], result.handoff or {}

    payload, handoff = anyio.run(run_case)

    expected_first = {
        "url_or_path": "https://docs.example.com/deploy",
        "title": "Deployment API",
        "source_kind": "primary_docs",
        "publisher_or_repository": "example/docs",
        "accessed_at": "2026-07-17",
        "supports_claims": ["deployment command semantics"],
        "freshness": "current",
        "notes": "official release documentation",
    }
    assert payload.frontmatter["evidence_items"][0] == expected_first
    assert handoff["evidence"][0] == expected_first
    assert (
        "- https://docs.example.com/deploy supports: deployment command semantics"
        in payload.body
    )
    assert "  - publisher_or_repository: example/docs" in payload.body


def test_obsidian_skill_artifact_publisher_marks_insufficient_evidence_handoff() -> (
    None
):
    """Needs-review artifacts with missing evidence should warn in handoff."""

    class FakeObsidianService:
        def __init__(self) -> None:
            self.payloads = []

        async def save_note(self, payload):  # type: ignore[no-untyped-def]
            self.payloads.append(payload)
            return _fake_skill_note(
                payload.note_id,
                body=payload.body,
                frontmatter=payload.frontmatter,
            )

        async def read_note(self, note_id: str):  # type: ignore[no-untyped-def]
            payload = self.payloads[0]
            return _fake_skill_note(
                note_id,
                body=payload.body,
                frontmatter=payload.frontmatter,
            )

        async def search(self, query, *, refresh: bool = True):  # type: ignore[no-untyped-def]
            class Hit:
                pass

            hit = Hit()
            hit.note = _fake_skill_note(self.payloads[0].note_id)
            hit.excerpt = "Unverified Browser Skill"
            hit.score = 1.0
            return [hit]

    async def run_case() -> dict[str, object]:
        obsidian_service = FakeObsidianService()
        publisher = ObsidianSkillArtifactPublisher(obsidian_service)  # type: ignore[arg-type]
        result = await publisher.publish_skill_artifact(
            job=_publisher_job(),
            artifact=SkillAcquisitionArtifact(
                title="Unverified Browser Skill",
                purpose="Use a browser workflow that still needs source review.",
                content="Draft the workflow and stop before active promotion.",
                status=ItemStatus.NEEDS_REVIEW,
            ),
        )
        return result.handoff or {}

    handoff = anyio.run(run_case)

    assert handoff["skill"]["review_status"] == "NEEDS_REVIEW"
    assert (
        "claim-linked evidence is missing or insufficient"
        in handoff["skill"]["limitations"]
    )
    assert handoff["warnings"] == [
        {
            "code": "artifact_needs_review",
            "message": (
                "Evidence or risk review is incomplete; keep the acquired "
                "skill in needs_review before active use."
            ),
        },
        {
            "code": "evidence_insufficient",
            "message": (
                "No claim-linked evidence was provided; reviewer "
                "verification is required before active promotion."
            ),
        },
    ]


def test_obsidian_skill_artifact_publisher_requires_two_sources_for_high_risk() -> None:
    """High-risk artifacts need multiple independent sources before saving."""

    async def run_case() -> str:
        publisher = ObsidianSkillArtifactPublisher(object())  # type: ignore[arg-type]
        with pytest.raises(LibrarianValidationError) as raised:
            await publisher.publish_skill_artifact(
                job=_publisher_job(),
                artifact=SkillAcquisitionArtifact(
                    title="Production Deployment Skill",
                    purpose="Deploy production services.",
                    content="Run production release commands.",
                    risk_level=RiskLevel.HIGH,
                    evidence_urls=["https://example.com/deploy"],
                    source_summary="Primary deployment docs reviewed.",
                ),
            )
        return str(raised.value)

    error_message = anyio.run(run_case)

    assert (
        error_message
        == "High-risk skill artifacts require at least two independent evidence sources"
    )


def test_obsidian_skill_artifact_publisher_rejects_same_source_high_risk_evidence() -> (
    None
):
    """High-risk artifacts need evidence from at least two independent sources."""

    async def run_case() -> str:
        publisher = ObsidianSkillArtifactPublisher(object())  # type: ignore[arg-type]
        with pytest.raises(LibrarianValidationError) as raised:
            await publisher.publish_skill_artifact(
                job=_publisher_job(),
                artifact=SkillAcquisitionArtifact(
                    title="Production Deployment Skill",
                    purpose="Deploy production services.",
                    content="Run production release commands.",
                    risk_level=RiskLevel.HIGH,
                    evidence_urls=[
                        "https://docs.example.com/deploy",
                        "https://docs.example.com/rollback",
                    ],
                    source_summary="Deployment and rollback docs reviewed.",
                ),
            )
        return str(raised.value)

    error_message = anyio.run(run_case)

    assert (
        error_message
        == "High-risk skill artifacts require at least two independent evidence sources"
    )


def test_obsidian_skill_artifact_publisher_fails_when_search_verification_misses() -> (
    None
):
    """Publisher should not complete when the saved skill is not searchable."""

    class SearchMissingObsidianService:
        def __init__(self) -> None:
            self.payload = None

        async def save_note(self, payload):  # type: ignore[no-untyped-def]
            self.payload = payload
            return _fake_skill_note(
                payload.note_id,
                body=payload.body,
                frontmatter=payload.frontmatter,
            )

        async def read_note(self, note_id: str):  # type: ignore[no-untyped-def]
            return _fake_skill_note(
                note_id,
                body=self.payload.body,
                frontmatter=self.payload.frontmatter,
            )

        async def search(self, query, *, refresh: bool = True):  # type: ignore[no-untyped-def]
            _ = query
            _ = refresh
            return []

    async def run_case() -> str:
        publisher = ObsidianSkillArtifactPublisher(
            SearchMissingObsidianService()  # type: ignore[arg-type]
        )
        with pytest.raises(LibrarianValidationError) as raised:
            await publisher.publish_skill_artifact(
                job=SkillAcquisitionJob(
                    id="skill-acquisition-1",
                    prompt="Need HTTP fakes",
                    agent_name="Hermes",
                    project="heterarchy-alexandria",
                    task_summary=None,
                    status=SkillAcquisitionJobStatus.ACCEPTED,
                    provider_id=None,
                    librarian_profile_id=None,
                    skill_id=None,
                    context_id=None,
                    result_summary=None,
                    evidence_urls=[],
                    error_message=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                    completed_at=None,
                ),
                artifact=SkillAcquisitionArtifact(
                    title="HTTP Boundary Fake",
                    purpose="Build deterministic HTTP boundary fakes.",
                    content="Use boundary fakes instead of internal mocks.",
                ),
            )
        return str(raised.value)

    error_message = anyio.run(run_case)

    assert error_message == "Published skill artifact was not found by search"


def test_obsidian_skill_artifact_publisher_fails_when_readback_contract_differs() -> (
    None
):
    """Publisher should fail before completion when saved body violates contract."""

    class MutatingReadbackObsidianService:
        def __init__(self) -> None:
            self.payload = None

        async def save_note(self, payload):  # type: ignore[no-untyped-def]
            self.payload = payload
            return _fake_skill_note(
                payload.note_id,
                body=payload.body,
                frontmatter=payload.frontmatter,
            )

        async def read_note(self, note_id: str):  # type: ignore[no-untyped-def]
            return _fake_skill_note(
                note_id,
                body="# Mutated\n",
                frontmatter=self.payload.frontmatter,
            )

        async def search(self, query, *, refresh: bool = True):  # type: ignore[no-untyped-def]
            _ = query
            _ = refresh
            return []

    async def run_case() -> str:
        publisher = ObsidianSkillArtifactPublisher(
            MutatingReadbackObsidianService()  # type: ignore[arg-type]
        )
        with pytest.raises(LibrarianValidationError) as raised:
            await publisher.publish_skill_artifact(
                job=SkillAcquisitionJob(
                    id="skill-acquisition-1",
                    prompt="Need HTTP fakes",
                    agent_name="Hermes",
                    project="heterarchy-alexandria",
                    task_summary=None,
                    status=SkillAcquisitionJobStatus.ACCEPTED,
                    provider_id=None,
                    librarian_profile_id=None,
                    skill_id=None,
                    context_id=None,
                    result_summary=None,
                    evidence_urls=[],
                    error_message=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                    completed_at=None,
                ),
                artifact=SkillAcquisitionArtifact(
                    title="HTTP Boundary Fake",
                    purpose="Build deterministic HTTP boundary fakes.",
                    content="Use boundary fakes instead of internal mocks.",
                ),
            )
        return str(raised.value)

    error_message = anyio.run(run_case)

    assert error_message == "Published skill artifact body read-back failed"
