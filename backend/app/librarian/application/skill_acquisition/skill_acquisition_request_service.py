"""Request orchestration for durable skill-acquisition jobs."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime

from app.librarian.application.skill_acquisition.skill_acquisition_provider_selector import (
    SkillAcquisitionProviderSelector,
)
from app.librarian.application.skill_acquisition.skill_acquisition_value_policy import (
    _job_id,
    _override_reason,
    _search_snapshot_sufficient,
    _search_snapshot_unavailable,
)
from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionJobCreate,
)
from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
    SkillAcquisitionJobStatus,
)
from app.librarian.domain.repositories.skill_acquisition_job_repository import (
    ISkillAcquisitionJobRepository,
)
from app.shared.exceptions.librarian_exceptions import LibrarianValidationError
from app.shared.types.extra_types import JSONObject

_GUIDANCE_SUMMARY = (
    "No executable librarian provider is available. Hermes should research the "
    "missing capability and submit a skill candidate through the agent path."
)
_ACCEPTED_SUMMARY = (
    "Skill acquisition job accepted. Poll this job for a sanitized result packet."
)
_CREDENTIAL_FAILURE = "Provider credentials unavailable"
_PROMPT_REFERENCE = "Prompts/Task Prompts/Librarian Operating Prompt v0.1.md"
_PROMPT_REFERENCE_HASH = hashlib.sha256(_PROMPT_REFERENCE.encode()).hexdigest()


class SkillAcquisitionRequestService:
    """Validate and persist initial skill-acquisition job requests."""

    def __init__(
        self,
        repository: ISkillAcquisitionJobRepository,
        provider_selector: SkillAcquisitionProviderSelector,
        now_provider: Callable[[], datetime],
    ) -> None:
        """Initialize request orchestration dependencies.

        Args:
            repository: Durable skill-acquisition job repository.
            provider_selector: Provider selection and execution policy.
            now_provider: Clock boundary for deterministic job creation.
        """
        self._repository = repository
        self._provider_selector = provider_selector
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
        if _search_snapshot_unavailable(search_snapshot):
            raise LibrarianValidationError(
                "Skill acquisition blocked by search readiness: SEARCH_UNAVAILABLE"
            )
        if _search_snapshot_sufficient(search_snapshot):
            raise LibrarianValidationError(
                "Skill acquisition blocked because an existing skill is sufficient"
            )
        now = self._now_provider()
        selected_provider = await self._provider_selector.select(provider_id)
        override_reason = _override_reason(
            search_snapshot=search_snapshot,
            acquisition_override_reason=acquisition_override_reason,
        )
        if selected_provider is None:
            status = SkillAcquisitionJobStatus.GUIDANCE_ONLY
            result_summary = _GUIDANCE_SUMMARY
            error_message = None if provider_id is None else "Provider not found"
            completed_at = now
            stage = SkillAcquisitionJobStage.GUIDANCE_READY
        elif await self._provider_selector.is_executable(selected_provider):
            status = SkillAcquisitionJobStatus.ACCEPTED
            result_summary = _ACCEPTED_SUMMARY
            error_message = None
            completed_at = None
            stage = SkillAcquisitionJobStage.REQUEST_ACCEPTED
        else:
            status = SkillAcquisitionJobStatus.FAILED
            result_summary = None
            error_message = _CREDENTIAL_FAILURE
            completed_at = now
            stage = SkillAcquisitionJobStage.PROVIDER_FAILED

        return await self._repository.create(
            SkillAcquisitionJobCreate(
                id=_job_id(prompt=prompt, agent_name=agent_name, now=now),
                prompt=prompt,
                agent_name=agent_name,
                project=project,
                task_summary=task_summary,
                status=status,
                provider_id=None if selected_provider is None else selected_provider.id,
                librarian_profile_id=librarian_profile_id,
                result_summary=result_summary,
                evidence_urls=(),
                error_message=error_message,
                created_at=now,
                updated_at=now,
                completed_at=completed_at,
                stage=stage,
                progress_summary=result_summary,
                repair_hint=error_message,
                search_snapshot=search_snapshot,
                acquisition_override_reason=override_reason,
                prompt_reference=_PROMPT_REFERENCE,
                prompt_reference_hash=_PROMPT_REFERENCE_HASH,
            )
        )
