"""Durable lifecycle updates for skill-acquisition jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.librarian.application.skill_acquisition.skill_acquisition_value_policy import (
    _redact_secret_text,
)
from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionJobUpdate,
)
from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
    SkillAcquisitionJobStatus,
)
from app.librarian.domain.repositories.skill_acquisition_job_repository import (
    ISkillAcquisitionJobRepository,
)
from app.shared.exceptions.librarian_exceptions import LibrarianResourceNotFoundError
from app.shared.types.extra_types import JSONObject


class SkillAcquisitionJobLifecycleService:
    """Read and transition durable skill-acquisition job state."""

    def __init__(
        self,
        repository: ISkillAcquisitionJobRepository,
        now_provider: Callable[[], datetime],
    ) -> None:
        """Initialize durable lifecycle dependencies.

        Args:
            repository: Durable job persistence port.
            now_provider: Clock boundary for deterministic transitions.
        """
        self._repository = repository
        self._now_provider = now_provider

    async def get_job(self, job_id: str) -> SkillAcquisitionJob:
        """Return one durable skill-acquisition job.

        Args:
            job_id: Job identifier.

        Returns:
            Matching job.
        """
        job = await self._repository.get(job_id)
        if job is None:
            raise LibrarianResourceNotFoundError(
                f"Skill acquisition job not found: {job_id}"
            )
        return job

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
        now = self._now_provider()
        existing = await self.get_job(job_id)
        job = await self._repository.update(
            job_id,
            SkillAcquisitionJobUpdate(
                status=SkillAcquisitionJobStatus.COMPLETED,
                result_summary=result_summary,
                evidence_urls=() if evidence_urls is None else tuple(evidence_urls),
                error_message=None,
                skill_id=skill_id,
                context_id=context_id,
                updated_at=now,
                completed_at=now,
                stage=stage,
                progress_summary=progress_summary or result_summary,
                skill_note_path=skill_note_path,
                reindex_status=reindex_status,
                verification_status=verification_status,
                handoff=handoff,
                repair_hint=repair_hint,
                search_snapshot=search_snapshot
                if search_snapshot is not None
                else existing.search_snapshot,
                acquisition_override_reason=acquisition_override_reason
                if acquisition_override_reason is not None
                else existing.acquisition_override_reason,
                prompt_reference=prompt_reference
                if prompt_reference is not None
                else existing.prompt_reference,
                prompt_reference_hash=prompt_reference_hash
                if prompt_reference_hash is not None
                else existing.prompt_reference_hash,
            ),
        )
        return job

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
        now = self._now_provider()
        existing = await self.get_job(job_id)
        sanitized_error = _redact_secret_text(error_message)
        sanitized_repair_hint = _redact_secret_text(repair_hint)
        job = await self._repository.update(
            job_id,
            SkillAcquisitionJobUpdate(
                status=SkillAcquisitionJobStatus.FAILED,
                result_summary=None,
                evidence_urls=(),
                error_message=sanitized_error,
                skill_id=skill_id,
                context_id=None,
                updated_at=now,
                completed_at=now,
                stage=stage,
                progress_summary=progress_summary,
                skill_note_path=skill_note_path,
                reindex_status=reindex_status,
                verification_status=verification_status,
                handoff=handoff,
                repair_hint=sanitized_repair_hint or sanitized_error,
                search_snapshot=existing.search_snapshot,
                acquisition_override_reason=existing.acquisition_override_reason,
                prompt_reference=existing.prompt_reference,
                prompt_reference_hash=existing.prompt_reference_hash,
            ),
        )
        return job
