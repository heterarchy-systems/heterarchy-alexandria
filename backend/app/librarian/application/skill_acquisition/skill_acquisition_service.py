"""Durable async skill-acquisition job service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.librarian.application.skill_acquisition.skill_acquisition_artifact_completion_service import (
    SkillAcquisitionArtifactCompletionService,
)
from app.librarian.application.skill_acquisition.skill_acquisition_job_lifecycle_service import (
    SkillAcquisitionJobLifecycleService,
)
from app.librarian.application.skill_acquisition.skill_acquisition_provider_selector import (
    SkillAcquisitionProviderSelector,
)
from app.librarian.application.skill_acquisition.skill_acquisition_request_service import (
    SkillAcquisitionRequestService,
)
from app.librarian.application.skill_artifacts.skill_artifact_publication_contracts import (
    PublishedSkillArtifact,
    SkillArtifactPublicationError,
    SkillArtifactPublisher,
)
from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
)
from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
)
from app.librarian.domain.repositories.skill_acquisition_job_repository import (
    ISkillAcquisitionJobRepository,
)
from app.shared.types.extra_types import JSONObject
from app.shared.types.types_convert_utils import now_utc

__all__ = (
    "PublishedSkillArtifact",
    "SkillAcquisitionService",
    "SkillArtifactPublicationError",
    "SkillArtifactPublisher",
)


class SkillAcquisitionService:
    """Create and inspect durable skill-acquisition jobs."""

    def __init__(
        self,
        repository: ISkillAcquisitionJobRepository,
        provider_repo: ILibrarianProviderRepository,
        secret_repo: IProviderSecretRepository,
        now_provider: Callable[[], datetime] = now_utc,
    ) -> None:
        """Initialize service dependencies.

        Args:
            repository: Durable job persistence port.
            provider_repo: Provider settings repository.
            secret_repo: Provider secret repository.
            now_provider: Clock boundary for deterministic tests.
        """
        self._repository = repository
        self._provider_selector = SkillAcquisitionProviderSelector(
            provider_repository=provider_repo,
            credential_repository=secret_repo,
            now_provider=now_provider,
        )
        self._request_service = SkillAcquisitionRequestService(
            repository=repository,
            provider_selector=self._provider_selector,
            now_provider=now_provider,
        )
        self._job_lifecycle = SkillAcquisitionJobLifecycleService(
            repository=repository,
            now_provider=now_provider,
        )
        self._artifact_completion = SkillAcquisitionArtifactCompletionService(
            job_lifecycle=self._job_lifecycle,
        )
        self._now_provider = now_provider

    async def request_job(
        self,
        prompt: str,
        agent_name: str = "Hermes",
        project: str | None = None,
        task_summary: str | None = None,
        provider_id: str | None = None,
        librarian_profile_id: str | None = None,
        search_snapshot: JSONObject | None = None,
        acquisition_override_reason: str | None = None,
    ) -> SkillAcquisitionJob:
        """Create one durable skill-acquisition job.

        Args:
            prompt: Missing-skill acquisition prompt.
            agent_name: Requesting agent.
            project: Optional project scope.
            task_summary: Optional current task summary.
            provider_id: Optional preferred provider.
            librarian_profile_id: Optional librarian profile.
            search_snapshot: Optional search-first decision snapshot.
            acquisition_override_reason: Explicit reason for starting without search.

        Returns:
            Created durable job.
        """
        return await self._request_service.request_job(
            prompt=prompt,
            agent_name=agent_name,
            project=project,
            task_summary=task_summary,
            provider_id=provider_id,
            librarian_profile_id=librarian_profile_id,
            search_snapshot=search_snapshot,
            acquisition_override_reason=acquisition_override_reason,
        )

    async def get_job(self, job_id: str) -> SkillAcquisitionJob:
        """Return one durable skill-acquisition job.

        Args:
            job_id: Job identifier.

        Returns:
            Matching job.
        """
        return await self._job_lifecycle.get_job(job_id)

    async def complete_job(
        self,
        job_id: str,
        result_summary: str,
        evidence_urls: list[str] | None = None,
        skill_id: str | None = None,
        context_id: str | None = None,
        skill_note_path: str | None = None,
        stage: SkillAcquisitionJobStage = SkillAcquisitionJobStage.HANDOFF_READY,
        progress_summary: str | None = None,
        reindex_status: str | None = None,
        verification_status: str | None = None,
        handoff: JSONObject | None = None,
        repair_hint: str | None = None,
        search_snapshot: JSONObject | None = None,
        acquisition_override_reason: str | None = None,
        prompt_reference: str | None = None,
        prompt_reference_hash: str | None = None,
    ) -> SkillAcquisitionJob:
        """Mark a durable job complete with sanitized result handles.

        Args:
            job_id: Job identifier.
            result_summary: Sanitized result summary.
            evidence_urls: Optional source URLs.
            skill_id: Deprecated persisted skill identifier; normally None after
                legacy relational skill CRUD removal.
            context_id: Optional persisted resume context identifier.
            skill_note_path: Optional Obsidian note path for the saved skill.
            stage: Observable completion-loop stage.
            progress_summary: Human-readable stage summary.
            reindex_status: Post-save index refresh status.
            verification_status: Exact read/search verification status.
            handoff: Structured resume payload for the current task.
            repair_hint: Optional repair guidance when completion is degraded.
            search_snapshot: Optional replacement search-first decision snapshot.
            acquisition_override_reason: Optional replacement override reason.
            prompt_reference: Optional replacement operating prompt reference.
            prompt_reference_hash: Optional replacement operating prompt hash.

        Returns:
            Updated job.
        """
        return await self._job_lifecycle.complete_job(
            job_id=job_id,
            result_summary=result_summary,
            evidence_urls=evidence_urls,
            skill_id=skill_id,
            context_id=context_id,
            skill_note_path=skill_note_path,
            stage=stage,
            progress_summary=progress_summary,
            reindex_status=reindex_status,
            verification_status=verification_status,
            handoff=handoff,
            repair_hint=repair_hint,
            search_snapshot=search_snapshot,
            acquisition_override_reason=acquisition_override_reason,
            prompt_reference=prompt_reference,
            prompt_reference_hash=prompt_reference_hash,
        )

    async def fail_job(
        self,
        job_id: str,
        error_message: str,
        stage: SkillAcquisitionJobStage = SkillAcquisitionJobStage.FAILED,
        progress_summary: str | None = None,
        skill_id: str | None = None,
        skill_note_path: str | None = None,
        reindex_status: str | None = None,
        verification_status: str | None = None,
        repair_hint: str | None = None,
        handoff: JSONObject | None = None,
    ) -> SkillAcquisitionJob:
        """Mark one durable job as failed and sanitize provider failure details.

        Args:
            job_id: Job identifier.
            error_message: Failure message from executor/provider.
            stage: Failure stage to expose on the durable job.
            progress_summary: Optional operator-readable failure progress.
            skill_id: Optional saved skill note id for partial publication.
            skill_note_path: Optional saved skill note path for partial publication.
            reindex_status: Optional reindex status for partial publication.
            verification_status: Optional verification status for partial publication.
            repair_hint: Optional repair hint; defaults to sanitized error.
            handoff: Optional structured retry/repair handoff.

        Returns:
            Updated job.
        """
        return await self._job_lifecycle.fail_job(
            job_id=job_id,
            error_message=error_message,
            stage=stage,
            progress_summary=progress_summary,
            skill_id=skill_id,
            skill_note_path=skill_note_path,
            reindex_status=reindex_status,
            verification_status=verification_status,
            repair_hint=repair_hint,
            handoff=handoff,
        )

    async def complete_with_skill_artifact(
        self,
        job_id: str,
        artifact: SkillAcquisitionArtifact,
        artifact_publisher: SkillArtifactPublisher | None = None,
    ) -> SkillAcquisitionJob:
        """Complete a job from an acquired skill artifact.

        Args:
            job_id: Durable job identifier.
            artifact: Structured acquired skill payload.
            artifact_publisher: Optional durable library publisher.

        Returns:
            Completed job with durable skill/context handles when published.
        """
        return await self._artifact_completion.complete_with_skill_artifact(
            job_id=job_id,
            artifact=artifact,
            artifact_publisher=artifact_publisher,
        )
