"""Publish acquired skill artifacts into the Obsidian skill library."""

from __future__ import annotations

from app.librarian.application.skill_artifacts.skill_artifact_document_renderer import (
    _skill_frontmatter,
    _skill_markdown_body,
    _skill_note_id,
    _skill_tags,
)
from app.librarian.application.skill_artifacts.skill_artifact_handoff_policy import (
    _handoff_payload,
)
from app.librarian.application.skill_artifacts.skill_artifact_publication_contracts import (
    PublishedSkillArtifact,
    SkillArtifactPublicationError,
    SkillArtifactPublisher,
)
from app.librarian.application.skill_artifacts.skill_artifact_validation_policy import (
    _validate_artifact,
)
from app.librarian.application.skill_artifacts.skill_artifact_verification_service import (
    SkillArtifactVerificationService,
)
from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
)
from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.exceptions.librarian_exceptions import LibrarianValidationError

_REQUIRED_SKILL_SECTIONS: tuple[str, ...] = (
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
)


class ObsidianSkillArtifactPublisher(SkillArtifactPublisher):
    """Publish acquired skills as draft Obsidian skill notes."""

    def __init__(self, obsidian_service: ObsidianService) -> None:
        """Create publisher.

        Args:
            obsidian_service: Obsidian application service.
        """
        self._obsidian_service = obsidian_service
        self._verification_service = SkillArtifactVerificationService(obsidian_service)

    async def publish_skill_artifact(
        self,
        job: SkillAcquisitionJob,
        artifact: SkillAcquisitionArtifact,
    ) -> PublishedSkillArtifact:
        """Save one skill artifact as a durable draft note.

        Args:
            job: Skill-acquisition job being completed.
            artifact: Structured acquired skill artifact.

        Returns:
            Durable skill handles for job completion.
        """
        _validate_artifact(artifact)
        body = _skill_markdown_body(job=job, artifact=artifact)
        frontmatter = _skill_frontmatter(job=job, artifact=artifact)
        note = await self._obsidian_service.save_note(
            ObsidianSaveNote(
                note_id=_skill_note_id(job.id),
                title=artifact.title,
                body=body,
                alexandria_type=AlexandriaNoteType.SKILL,
                tags=tuple(_skill_tags(artifact)),
                status="draft",
                project=job.project,
                source="skill_acquisition",
                frontmatter=frontmatter,
            )
        )
        try:
            await self._verification_service.verify(
                note_id=note.note_id,
                title=artifact.title,
                project=job.project,
                expected_body=body,
                expected_frontmatter=frontmatter,
            )
        except LibrarianValidationError as error:
            raise SkillArtifactPublicationError(
                str(error),
                skill_id=note.note_id,
                skill_note_path=note.relative_path,
                stage=SkillAcquisitionJobStage.SKILL_SAVED,
                verification_status="failed",
            ) from error
        handoff = _handoff_payload(
            job=job,
            artifact=artifact,
            note_id=note.note_id,
            note_path=note.relative_path,
        )
        return PublishedSkillArtifact(
            skill_id=note.note_id,
            context_id=None,
            result_summary=f"Saved and verified draft skill note: {note.relative_path}",
            skill_note_path=note.relative_path,
            stage=SkillAcquisitionJobStage.HANDOFF_READY,
            progress_summary=(
                "Searched, saved, reindexed, search-verified, and read-back "
                f"verified draft skill note: {note.relative_path}"
            ),
            reindex_status="succeeded",
            verification_status="verified",
            handoff=handoff,
            repair_hint=None,
        )
