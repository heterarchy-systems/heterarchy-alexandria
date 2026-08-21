"""Background skill-acquisition runner behavior tests."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio
import pytest
from app.librarian.application.skill_acquisition.skill_acquisition_runner import (
    SkillAcquisitionExecutionRequest,
    SkillAcquisitionRunner,
)
from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
)
from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStatus,
)
from app.shared.exceptions.librarian_exceptions import (
    LibrarianSkillAcquisitionArtifactError,
    LibrarianSkillAcquisitionExecutionError,
    LibrarianSkillAcquisitionProviderError,
)

_NOW = datetime(2026, 5, 19, 18, 25, tzinfo=UTC)


class FakeSkillAcquisitionService:
    """Service fake exposing the runner-owned job operations."""

    def __init__(self, job: SkillAcquisitionJob) -> None:
        """Initialize fake service state."""
        self.job = job
        self.completed_artifact: SkillAcquisitionArtifact | None = None
        self.artifact_publisher_seen = False
        self.failure_message: str | None = None

    async def get_job(self, job_id: str) -> SkillAcquisitionJob:
        """Return the current fake job."""
        assert job_id == self.job.id
        return self.job

    async def complete_with_skill_artifact(
        self,
        *,
        job_id: str,
        artifact: SkillAcquisitionArtifact,
        artifact_publisher=None,  # type: ignore[no-untyped-def]
    ) -> SkillAcquisitionJob:
        """Record completion and return a completed job with durable handles."""
        assert job_id == self.job.id
        self.completed_artifact = artifact
        self.artifact_publisher_seen = artifact_publisher is not None
        self.job = SkillAcquisitionJob(
            id=self.job.id,
            prompt=self.job.prompt,
            agent_name=self.job.agent_name,
            project=self.job.project,
            task_summary=self.job.task_summary,
            status=SkillAcquisitionJobStatus.COMPLETED,
            provider_id=self.job.provider_id,
            librarian_profile_id=self.job.librarian_profile_id,
            skill_id=None,
            context_id="00000000-0000-4000-8000-000000000888",
            result_summary="Provider returned a skill artifact.",
            evidence_urls=list(artifact.evidence_urls),
            error_message=None,
            created_at=self.job.created_at,
            updated_at=_NOW,
            completed_at=_NOW,
        )
        return self.job

    async def fail_job(self, *, job_id: str, error_message: str) -> SkillAcquisitionJob:
        """Record sanitized failure and return a terminal failed job."""
        assert job_id == self.job.id
        self.failure_message = error_message
        self.job = SkillAcquisitionJob(
            id=self.job.id,
            prompt=self.job.prompt,
            agent_name=self.job.agent_name,
            project=self.job.project,
            task_summary=self.job.task_summary,
            status=SkillAcquisitionJobStatus.FAILED,
            provider_id=self.job.provider_id,
            librarian_profile_id=self.job.librarian_profile_id,
            skill_id=None,
            context_id=None,
            result_summary=None,
            evidence_urls=[],
            error_message=error_message,
            created_at=self.job.created_at,
            updated_at=_NOW,
            completed_at=_NOW,
        )
        return self.job


class RecordingExecutor:
    """Executor fake that returns one structured skill artifact."""

    def __init__(self, artifact: SkillAcquisitionArtifact) -> None:
        """Initialize fake executor state."""
        self.artifact = artifact
        self.requests: list[SkillAcquisitionExecutionRequest] = []

    async def acquire_skill(
        self,
        request: SkillAcquisitionExecutionRequest,
    ) -> SkillAcquisitionArtifact:
        """Record the execution request and return an artifact."""
        self.requests.append(request)
        return self.artifact


class FailingExecutor:
    """Executor fake that raises a provider-like secret-bearing error."""

    def __init__(self) -> None:
        """Initialize fake executor state."""
        self.called = False

    async def acquire_skill(
        self,
        request: SkillAcquisitionExecutionRequest,
    ) -> SkillAcquisitionArtifact:
        """Raise a provider failure that must be sanitized by the runner."""
        self.called = True
        _ = request
        raise RuntimeError("provider failed with api_key=SECRET-KEY token=SECRET")


class DomainFailingExecutor:
    """Executor fake that raises a known skill-acquisition domain failure."""

    def __init__(self, error: Exception) -> None:
        """Initialize fake executor state."""
        self.error = error

    async def acquire_skill(
        self,
        request: SkillAcquisitionExecutionRequest,
    ) -> SkillAcquisitionArtifact:
        """Raise a known domain failure for runner mapping."""
        _ = request
        raise self.error


def _accepted_job() -> SkillAcquisitionJob:
    return SkillAcquisitionJob(
        id="skill-acquisition-1",
        prompt="Need a deterministic browser automation skill",
        agent_name="Hermes",
        project="heterarchy-alexandria",
        task_summary="Continue the browser verification task.",
        status=SkillAcquisitionJobStatus.ACCEPTED,
        provider_id="provider-1",
        librarian_profile_id="profile-1",
        skill_id=None,
        context_id=None,
        result_summary="Skill acquisition job accepted.",
        evidence_urls=[],
        error_message=None,
        created_at=_NOW,
        updated_at=_NOW,
        completed_at=None,
    )


def test_runner_persists_executor_artifact_when_job_is_accepted() -> None:
    """Accepted jobs should execute once and complete with durable handles."""

    async def run_case() -> tuple[
        SkillAcquisitionJob, list[SkillAcquisitionExecutionRequest], bool
    ]:
        service = FakeSkillAcquisitionService(_accepted_job())
        executor = RecordingExecutor(
            SkillAcquisitionArtifact(
                title="Browser automation verification",
                purpose="Verify browser tasks through deterministic automation.",
                content="Use stable selectors and capture console failures.",
                summary="Browser verification skill.",
                evidence_urls=["https://example.com/browser"],
                source_summary="Provider produced a structured skill artifact.",
            )
        )
        runner = SkillAcquisitionRunner(service=service, executor=executor)

        completed = await runner.run_job(
            "skill-acquisition-1",
            artifact_publisher=object(),  # type: ignore[arg-type]
        )

        return completed, executor.requests, service.artifact_publisher_seen

    completed, requests, artifact_publisher_seen = anyio.run(run_case)

    assert completed.status is SkillAcquisitionJobStatus.COMPLETED
    assert completed.skill_id is None
    assert completed.context_id == "00000000-0000-4000-8000-000000000888"
    assert requests == [
        SkillAcquisitionExecutionRequest(
            job_id="skill-acquisition-1",
            prompt="Need a deterministic browser automation skill",
            agent_name="Hermes",
            project="heterarchy-alexandria",
            task_summary="Continue the browser verification task.",
            provider_id="provider-1",
            librarian_profile_id="profile-1",
        )
    ]
    assert artifact_publisher_seen is True


def test_runner_skips_terminal_jobs_when_retried() -> None:
    """Terminal jobs should not call the executor again."""

    async def run_case() -> tuple[SkillAcquisitionJob, int]:
        terminal_job = _accepted_job().__class__(
            id="skill-acquisition-1",
            prompt="Need a deterministic browser automation skill",
            agent_name="Hermes",
            project="heterarchy-alexandria",
            task_summary="Continue the browser verification task.",
            status=SkillAcquisitionJobStatus.COMPLETED,
            provider_id="provider-1",
            librarian_profile_id="profile-1",
            skill_id="00000000-0000-4000-8000-000000000777",
            context_id="00000000-0000-4000-8000-000000000888",
            result_summary="Already completed.",
            evidence_urls=[],
            error_message=None,
            created_at=_NOW,
            updated_at=_NOW,
            completed_at=_NOW,
        )
        service = FakeSkillAcquisitionService(terminal_job)
        executor = RecordingExecutor(
            SkillAcquisitionArtifact(
                title="Should not run",
                purpose="Should not run.",
                content="Should not run.",
            )
        )
        runner = SkillAcquisitionRunner(service=service, executor=executor)

        result = await runner.run_job("skill-acquisition-1")

        return result, len(executor.requests)

    result, request_count = anyio.run(run_case)

    assert result.status is SkillAcquisitionJobStatus.COMPLETED
    assert result.skill_id == "00000000-0000-4000-8000-000000000777"
    assert request_count == 0


def test_runner_fails_job_with_sanitized_error_when_executor_raises() -> None:
    """Provider failures should persist sanitized job errors without secrets."""

    async def run_case() -> tuple[SkillAcquisitionJob, str | None, bool]:
        service = FakeSkillAcquisitionService(_accepted_job())
        executor = FailingExecutor()
        runner = SkillAcquisitionRunner(service=service, executor=executor)

        failed = await runner.run_job("skill-acquisition-1")

        return failed, service.failure_message, executor.called

    failed, failure_message, executor_called = anyio.run(run_case)

    serialized = f"{failed}{failure_message}"
    assert failed.status is SkillAcquisitionJobStatus.FAILED
    assert failed.result_available is False
    assert failure_message == "Skill acquisition executor failed"
    assert executor_called is True
    assert "SECRET" not in serialized
    assert "api_key" not in serialized
    assert "token" not in serialized


@pytest.mark.parametrize(
    ("error", "expected_message"),
    [
        (
            LibrarianSkillAcquisitionProviderError("provider unavailable"),
            "Skill acquisition provider failed",
        ),
        (
            LibrarianSkillAcquisitionExecutionError("provider execution failed"),
            "Skill acquisition execution failed",
        ),
        (
            LibrarianSkillAcquisitionArtifactError("strict JSON required"),
            "Skill acquisition artifact invalid",
        ),
    ],
)
def test_runner_records_domain_failure_message_when_executor_raises_known_error(
    error: Exception,
    expected_message: str,
) -> None:
    """Known executor domain failures should keep distinct persisted messages."""

    async def run_case() -> tuple[SkillAcquisitionJob, str | None]:
        service = FakeSkillAcquisitionService(_accepted_job())
        executor = DomainFailingExecutor(error)
        runner = SkillAcquisitionRunner(service=service, executor=executor)

        failed = await runner.run_job("skill-acquisition-1")

        return failed, service.failure_message

    failed, failure_message = anyio.run(run_case)

    assert failed.status is SkillAcquisitionJobStatus.FAILED
    assert failure_message == expected_message
