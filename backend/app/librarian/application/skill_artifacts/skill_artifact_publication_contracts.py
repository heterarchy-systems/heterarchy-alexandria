"""Contracts for durable publication of acquired skill artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
)
from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
)
from app.shared.exceptions.librarian_exceptions import LibrarianValidationError
from app.shared.types.extra_types import JSONObject


class SkillArtifactPublicationError(LibrarianValidationError):
    """Raised when publication fails after partial durable handles exist."""

    def __init__(
        self,
        message: str,
        skill_id: str | None = None,
        skill_note_path: str | None = None,
        stage: SkillAcquisitionJobStage = SkillAcquisitionJobStage.FAILED,
        reindex_status: str | None = None,
        verification_status: str | None = None,
    ) -> None:
        """Create publication failure with optional saved handles.

        Args:
            message: Sanitized failure message.
            skill_id: Durable skill note id when save already succeeded.
            skill_note_path: Durable skill note path when save already succeeded.
            stage: Observable stage where publication failed.
            reindex_status: Optional reindex status at failure time.
            verification_status: Optional verification status at failure time.
        """
        super().__init__(message)
        self.skill_id = skill_id
        self.skill_note_path = skill_note_path
        self.stage = stage
        self.reindex_status = reindex_status
        self.verification_status = verification_status


@dataclass(frozen=True, slots=True)
class PublishedSkillArtifact:
    """Durable publication result for an acquired skill artifact."""

    skill_id: str
    context_id: str | None = None
    result_summary: str | None = None
    skill_note_path: str | None = None
    stage: SkillAcquisitionJobStage = SkillAcquisitionJobStage.HANDOFF_READY
    progress_summary: str | None = None
    reindex_status: str | None = None
    verification_status: str | None = None
    handoff: JSONObject | None = None
    repair_hint: str | None = None


class SkillArtifactPublisher(ABC):
    """Boundary for publishing acquired skills to the durable library."""

    @abstractmethod
    async def publish_skill_artifact(
        self,
        job: SkillAcquisitionJob,
        artifact: SkillAcquisitionArtifact,
    ) -> PublishedSkillArtifact:
        """Publish one acquired skill artifact.

        Args:
            job: Skill-acquisition job being completed.
            artifact: Structured skill artifact.

        Returns:
            Durable skill publication handles.
        """
