"""Artifact completion orchestration for skill-acquisition jobs."""

from __future__ import annotations

from app.librarian.application.skill_acquisition.skill_acquisition_handoff_policy import (
    _completion_handoff_error,
    _publication_error_reindex_status,
    _publication_error_skill_id,
    _publication_error_skill_note_path,
    _publication_error_verification_status,
    _publication_failure_stage,
    _repair_handoff,
)
from app.librarian.application.skill_acquisition.skill_acquisition_job_lifecycle_service import (
    SkillAcquisitionJobLifecycleService,
)
from app.librarian.application.skill_acquisition.skill_acquisition_value_policy import (
    _clean_items,
    _completion_summary,
)
from app.librarian.application.skill_artifacts.skill_artifact_publication_contracts import (
    SkillArtifactPublisher,
)
from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
)
from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
    SkillAcquisitionJobStatus,
)
from app.librarian.domain.event_enum.skill_acquisition_enums import ItemStatus
from app.shared.exceptions.librarian_exceptions import LibrarianValidationError
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.types.extra_types import JSONObject


class SkillAcquisitionArtifactCompletionService:
    """Publish acquired artifacts and transition durable jobs to terminal state."""

    def __init__(
        self,
        job_lifecycle: SkillAcquisitionJobLifecycleService,
    ) -> None:
        """Initialize artifact completion dependencies.

        Args:
            job_lifecycle: Durable job read and transition service.
        """
        self._job_lifecycle = job_lifecycle

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
        job = await self._job_lifecycle.get_job(job_id)
        if job.status is SkillAcquisitionJobStatus.COMPLETED:
            return job
        if job.status not in {
            SkillAcquisitionJobStatus.ACCEPTED,
            SkillAcquisitionJobStatus.GUIDANCE_ONLY,
        }:
            raise LibrarianValidationError("Skill acquisition job is not completable")
        if artifact.activate or artifact.status is ItemStatus.ACTIVE:
            raise LibrarianValidationError(
                "Skill acquisition artifacts cannot be auto-activated"
            )

        evidence_urls = _clean_items(artifact.evidence_urls)
        result_summary = _completion_summary(
            artifact=artifact,
        )
        skill_id: str | None = None
        context_id: str | None = None
        skill_note_path: str | None = None
        stage = SkillAcquisitionJobStage.ARTIFACT_RECEIVED
        progress_summary = result_summary
        reindex_status: str | None = None
        verification_status: str | None = None
        handoff: JSONObject | None = None
        repair_hint: str | None = None
        if artifact_publisher is not None:
            try:
                published = await artifact_publisher.publish_skill_artifact(
                    job=job,
                    artifact=artifact,
                )
            except LibrarianValidationError as error:
                failure_stage = _publication_failure_stage(error)
                return await self._job_lifecycle.fail_job(
                    job_id=job.id,
                    error_message=str(error),
                    stage=failure_stage,
                    progress_summary="Skill artifact publication failed validation.",
                    skill_id=_publication_error_skill_id(error),
                    skill_note_path=_publication_error_skill_note_path(error),
                    reindex_status=_publication_error_reindex_status(error),
                    verification_status=_publication_error_verification_status(error),
                    repair_hint=str(error),
                    handoff=_repair_handoff(
                        job=job,
                        error_message=str(error),
                        stage=failure_stage,
                        skill_id=_publication_error_skill_id(error),
                        skill_note_path=_publication_error_skill_note_path(error),
                    ),
                )
            except ObsidianValidationError as error:
                return await self._job_lifecycle.fail_job(
                    job_id=job.id,
                    error_message=str(error),
                    progress_summary="Skill artifact publication was blocked by Obsidian guardrails.",
                    repair_hint=str(error),
                    handoff=_repair_handoff(job=job, error_message=str(error)),
                )
            except Exception:
                return await self._job_lifecycle.fail_job(
                    job_id=job.id,
                    error_message="Skill artifact publication failed",
                    progress_summary="Skill artifact publication failed unexpectedly.",
                    repair_hint="Retry completion after checking Obsidian save/search readiness.",
                    handoff=_repair_handoff(
                        job=job,
                        error_message="Skill artifact publication failed",
                    ),
                )
            validation_error = _completion_handoff_error(published.handoff)
            if validation_error is not None:
                return await self._job_lifecycle.fail_job(
                    job_id=job.id,
                    error_message=validation_error,
                    progress_summary="Skill acquisition handoff failed validation.",
                    repair_hint=validation_error,
                    handoff=_repair_handoff(job=job, error_message=validation_error),
                )
            skill_id = published.skill_id
            context_id = published.context_id
            skill_note_path = published.skill_note_path
            stage = published.stage
            progress_summary = published.progress_summary or published.result_summary
            reindex_status = published.reindex_status
            verification_status = published.verification_status
            handoff = published.handoff
            repair_hint = published.repair_hint
            if published.result_summary is not None:
                result_summary = published.result_summary
        completed = await self._job_lifecycle.complete_job(
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
        )
        return completed
