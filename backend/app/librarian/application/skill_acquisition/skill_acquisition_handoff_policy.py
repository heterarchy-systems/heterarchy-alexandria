"""Publication failure and handoff policies for skill acquisition."""

from __future__ import annotations

from app.librarian.application.skill_acquisition.skill_acquisition_value_policy import (
    _redact_secret_text,
)
from app.librarian.application.skill_artifacts.skill_artifact_publication_contracts import (
    SkillArtifactPublicationError,
)
from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
    SkillAcquisitionJobStatus,
)
from app.shared.exceptions.librarian_exceptions import LibrarianValidationError
from app.shared.types.extra_types import JSONObject


def _publication_failure_stage(
    error: LibrarianValidationError,
) -> SkillAcquisitionJobStage:
    """Execute publication failure stage.

    Args:
        error: Error value being processed.

    Returns:
        SkillAcquisitionJobStage result produced by publication failure stage.
    """
    if isinstance(error, SkillArtifactPublicationError):
        return error.stage
    normalized = str(error).lower()
    if "read-back" in normalized or "search" in normalized or "verified" in normalized:
        return SkillAcquisitionJobStage.SKILL_SAVED
    return SkillAcquisitionJobStage.FAILED


def _publication_error_skill_id(error: LibrarianValidationError) -> str | None:
    """Execute publication error skill id.

    Args:
        error: Error value being processed.

    Returns:
        str | None result produced by publication error skill id.
    """
    if isinstance(error, SkillArtifactPublicationError):
        return error.skill_id
    return None


def _publication_error_skill_note_path(error: LibrarianValidationError) -> str | None:
    """Execute publication error skill note path.

    Args:
        error: Error value being processed.

    Returns:
        str | None result produced by publication error skill note path.
    """
    if isinstance(error, SkillArtifactPublicationError):
        return error.skill_note_path
    return None


def _publication_error_reindex_status(error: LibrarianValidationError) -> str | None:
    """Execute publication error reindex status.

    Args:
        error: Error value being processed.

    Returns:
        str | None result produced by publication error reindex status.
    """
    if isinstance(error, SkillArtifactPublicationError):
        return error.reindex_status
    return None


def _publication_error_verification_status(
    error: LibrarianValidationError,
) -> str | None:
    """Execute publication error verification status.

    Args:
        error: Error value being processed.

    Returns:
        str | None result produced by publication error verification status.
    """
    if isinstance(error, SkillArtifactPublicationError):
        return error.verification_status
    return None


def _completion_handoff_error(handoff: JSONObject | None) -> str | None:
    """Execute completion handoff error.

    Args:
        handoff: Handoff used by this operation.

    Returns:
        str | None result produced by completion handoff error.
    """
    if handoff is None:
        return "Skill acquisition handoff is required"
    required_fields = (
        "current_task",
        "evidence",
        "job",
        "persistence",
        "progress_summary",
        "skill",
    )
    missing_fields = sorted(field for field in required_fields if field not in handoff)
    if missing_fields:
        return "Skill acquisition handoff missing required fields: " + ", ".join(
            missing_fields
        )
    if (
        not isinstance(handoff["progress_summary"], str)
        or not handoff["progress_summary"].strip()
    ):
        return "Skill acquisition handoff progress_summary is required"
    evidence = handoff["evidence"]
    if not isinstance(evidence, list):
        return "Skill acquisition handoff evidence must be a list"
    skill = handoff["skill"]
    if not isinstance(skill, dict):
        return "Skill acquisition handoff skill must be an object"
    missing_skill_fields = sorted(
        field for field in ("id", "path", "status") if field not in skill
    )
    if missing_skill_fields:
        return "Skill acquisition handoff skill missing required fields: " + ", ".join(
            missing_skill_fields
        )
    persistence = handoff["persistence"]
    if not isinstance(persistence, dict):
        return "Skill acquisition handoff persistence must be an object"
    missing_persistence_fields = sorted(
        field
        for field in ("reindex_status", "saved", "verified")
        if field not in persistence
    )
    if missing_persistence_fields:
        return (
            "Skill acquisition handoff persistence missing required fields: "
            + ", ".join(missing_persistence_fields)
        )
    if persistence.get("saved") is not True or persistence.get("verified") is not True:
        return "Skill acquisition handoff persistence must be saved and verified"
    current_task = handoff["current_task"]
    if not isinstance(current_task, dict):
        return "Skill acquisition handoff current_task must be an object"
    missing_task_fields = sorted(
        field
        for field in ("next_steps", "resume_summary", "stop_condition")
        if field not in current_task
    )
    if missing_task_fields:
        return (
            "Skill acquisition handoff current_task missing required fields: "
            + ", ".join(missing_task_fields)
        )
    if (
        not isinstance(current_task["resume_summary"], str)
        or not current_task["resume_summary"].strip()
    ):
        return "Skill acquisition handoff current_task resume_summary is required"
    if not isinstance(current_task["next_steps"], list):
        return "Skill acquisition handoff current_task next_steps must be a list"
    if (
        not isinstance(current_task["stop_condition"], str)
        or not current_task["stop_condition"].strip()
    ):
        return "Skill acquisition handoff current_task stop_condition is required"
    return None


def _repair_handoff(
    job: SkillAcquisitionJob,
    error_message: str,
    stage: SkillAcquisitionJobStage = SkillAcquisitionJobStage.FAILED,
    skill_id: str | None = None,
    skill_note_path: str | None = None,
) -> JSONObject:
    """Execute repair handoff.

    Args:
        job: Job used by this operation.
        error_message: Error message used by this operation.
        stage: Stage used by this operation.
        skill_id: Identifier for skill.
        skill_note_path: Skill note path used by this operation.

    Returns:
        JSONObject result produced by repair handoff.
    """
    payload: JSONObject = {
        "decision": "skill_acquisition_repair_required",
        "job": {
            "id": job.id,
            "status": SkillAcquisitionJobStatus.FAILED.value,
            "stage": stage.value,
        },
        "repair": {
            "retry_key": job.id,
            "hint": _redact_secret_text(error_message)
            or "Retry skill acquisition completion.",
        },
    }
    if skill_id is not None or skill_note_path is not None:
        payload["saved_handles"] = {
            "skill_id": skill_id,
            "skill_note_path": skill_note_path,
        }
    return payload
