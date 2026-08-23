"""Read-back and search verification for published skill artifacts."""

from __future__ import annotations

from app.librarian.application.skill_artifacts.skill_artifact_validation_policy import (
    _verify_saved_contract,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSearchQuery
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.exceptions.librarian_exceptions import LibrarianValidationError
from app.shared.types.extra_types import JSONObject


class SkillArtifactVerificationService:
    """Verify saved skill notes through exact read-back and indexed search."""

    def __init__(self, obsidian_service: ObsidianService) -> None:
        """Initialize verification dependencies.

        Args:
            obsidian_service: Obsidian note read and search boundary.
        """
        self._obsidian_service = obsidian_service

    async def verify(
        self,
        note_id: str,
        title: str,
        project: str | None,
        expected_body: str,
        expected_frontmatter: JSONObject,
    ) -> None:
        """Verify a skill artifact against its declared contract.

        Args:
            note_id: Stable identifier of the note or skill artifact.
            title: Human-readable title for the note or artifact.
            project: Project scope associated with the artifact or context.
            expected_body: Expected Markdown body used to verify the skill artifact.
            expected_frontmatter: Expected frontmatter used to verify the skill artifact.
        """
        saved = await self._obsidian_service.read_note(note_id)
        if saved.note_id != note_id:
            raise LibrarianValidationError("Published skill artifact read-back failed")
        _verify_saved_contract(
            saved_body=saved.body,
            saved_frontmatter=saved.frontmatter,
            expected_body=expected_body,
            expected_frontmatter=expected_frontmatter,
        )
        hits = await self._obsidian_service.search(
            ObsidianSearchQuery(
                query=title,
                limit=10,
                alexandria_type=AlexandriaNoteType.SKILL,
                project=project,
                tags=("skill-acquisition",),
            ),
            refresh=True,
        )
        if not any(hit.note.note_id == note_id for hit in hits):
            raise LibrarianValidationError(
                "Published skill artifact was not found by search"
            )
