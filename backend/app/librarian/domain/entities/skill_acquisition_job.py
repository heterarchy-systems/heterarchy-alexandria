"""Durable skill-acquisition job read models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
    SkillAcquisitionJobStatus,
)
from app.shared.types.extra_types import JSONObject


@dataclass(slots=True)
class SkillAcquisitionJob:
    """Read model for one librarian-owned skill-acquisition job."""

    id: str
    prompt: str
    agent_name: str
    project: str | None
    task_summary: str | None
    status: SkillAcquisitionJobStatus
    provider_id: str | None
    librarian_profile_id: str | None
    skill_id: str | None
    context_id: str | None
    result_summary: str | None
    evidence_urls: tuple[str, ...]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    stage: SkillAcquisitionJobStage | None = None
    progress_summary: str | None = None
    skill_note_path: str | None = None
    reindex_status: str | None = None
    verification_status: str | None = None
    handoff: JSONObject | None = None
    repair_hint: str | None = None
    search_snapshot: JSONObject | None = None
    acquisition_override_reason: str | None = None
    prompt_reference: str | None = None
    prompt_reference_hash: str | None = None

    def __post_init__(self) -> None:
        """Normalize evidence URLs to an immutable sequence."""
        self.evidence_urls = tuple(self.evidence_urls)

    @property
    def result_available(self) -> bool:
        """Return whether the job produced a completed result.

        Returns:
            True when completion produced a summary or durable result handle.
        """
        return self.status is SkillAcquisitionJobStatus.COMPLETED and (
            self.result_summary is not None
            or self.skill_id is not None
            or self.context_id is not None
        )
