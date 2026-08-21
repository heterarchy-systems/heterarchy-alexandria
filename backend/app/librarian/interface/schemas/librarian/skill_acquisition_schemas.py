"""Skill-acquisition job API schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
    SkillAcquisitionJobStatus,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONValue


class SkillAcquisitionJobRequest(StrictSchemaModel):
    """Request payload for autonomous durable skill acquisition."""

    prompt: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Prompt for this skill acquisition job request."),
    ]
    agent_name: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Agent name for this skill acquisition job request."),
    ] = "Hermes"
    project: Annotated[
        str | None, described_field("Project for this skill acquisition job request.")
    ] = None
    task_summary: Annotated[
        str | None,
        described_field("Task summary for this skill acquisition job request."),
    ] = None
    search_snapshot: Annotated[
        dict[str, JSONValue] | None,
        described_field("Search snapshot for this skill acquisition job request."),
    ] = None
    acquisition_override_reason: Annotated[
        str | None,
        described_field(
            "Acquisition override reason for this skill acquisition job request."
        ),
    ] = None


class SkillAcquisitionJobResponse(StrictSchemaModel):
    """Public response for one durable skill-acquisition job."""

    id: Annotated[
        str,
        described_field("Stable identifier for this skill acquisition job response."),
    ]
    prompt: Annotated[
        str, described_field("Prompt for this skill acquisition job response.")
    ]
    agent_name: Annotated[
        str, described_field("Agent name for this skill acquisition job response.")
    ]
    project: Annotated[
        str | None, described_field("Project for this skill acquisition job response.")
    ]
    task_summary: Annotated[
        str | None,
        described_field("Task summary for this skill acquisition job response."),
    ]
    status: Annotated[
        SkillAcquisitionJobStatus,
        described_field("Status for this skill acquisition job response."),
    ]
    skill_id: Annotated[
        str | None,
        described_field("Skill identifier for this skill acquisition job response."),
    ]
    context_id: Annotated[
        str | None,
        described_field("Context identifier for this skill acquisition job response."),
    ]
    result_summary: Annotated[
        str | None,
        described_field("Result summary for this skill acquisition job response."),
    ]
    evidence_urls: Annotated[
        list[str],
        described_field("Evidence urls for this skill acquisition job response."),
    ]
    error_message: Annotated[
        str | None,
        described_field("Error message for this skill acquisition job response."),
    ]
    result_available: Annotated[
        bool,
        described_field("Result available for this skill acquisition job response."),
    ]
    created_at: Annotated[
        AwareTimestamp,
        described_field("Creation timestamp for this skill acquisition job response."),
    ]
    updated_at: Annotated[
        AwareTimestamp,
        described_field(
            "Last-update timestamp for this skill acquisition job response."
        ),
    ]
    completed_at: Annotated[
        AwareTimestamp | None,
        described_field("Completed at for this skill acquisition job response."),
    ]
    stage: Annotated[
        SkillAcquisitionJobStage | None,
        described_field("Stage for this skill acquisition job response."),
    ]
    progress_summary: Annotated[
        str | None,
        described_field("Progress summary for this skill acquisition job response."),
    ]
    skill_note_path: Annotated[
        str | None,
        described_field("Skill note path for this skill acquisition job response."),
    ]
    reindex_status: Annotated[
        str | None,
        described_field("Reindex status for this skill acquisition job response."),
    ]
    verification_status: Annotated[
        str | None,
        described_field("Verification status for this skill acquisition job response."),
    ]
    handoff: Annotated[
        dict[str, JSONValue] | None,
        described_field("Handoff for this skill acquisition job response."),
    ]
    repair_hint: Annotated[
        str | None,
        described_field("Repair hint for this skill acquisition job response."),
    ]
    search_snapshot: Annotated[
        dict[str, JSONValue] | None,
        described_field("Search snapshot for this skill acquisition job response."),
    ]
    acquisition_override_reason: Annotated[
        str | None,
        described_field(
            "Acquisition override reason for this skill acquisition job response."
        ),
    ]
    prompt_reference: Annotated[
        str | None,
        described_field("Prompt reference for this skill acquisition job response."),
    ]
    prompt_reference_hash: Annotated[
        str | None,
        described_field(
            "Prompt reference hash for this skill acquisition job response."
        ),
    ]


def skill_acquisition_job_response(
    job: SkillAcquisitionJob,
) -> SkillAcquisitionJobResponse:
    """Map a job read model into a public response schema.

    Args:
        job: Durable job read model.

    Returns:
        Public API response schema.
    """
    response = SkillAcquisitionJobResponse(
        id=job.id,
        prompt=job.prompt,
        agent_name=job.agent_name,
        project=job.project,
        task_summary=job.task_summary,
        status=job.status,
        skill_id=job.skill_id,
        context_id=job.context_id,
        result_summary=job.result_summary,
        evidence_urls=list(job.evidence_urls),
        error_message=job.error_message,
        result_available=job.result_available,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        stage=job.stage,
        progress_summary=job.progress_summary,
        skill_note_path=job.skill_note_path,
        reindex_status=job.reindex_status,
        verification_status=job.verification_status,
        handoff=job.handoff,
        repair_hint=job.repair_hint,
        search_snapshot=job.search_snapshot,
        acquisition_override_reason=job.acquisition_override_reason,
        prompt_reference=job.prompt_reference,
        prompt_reference_hash=job.prompt_reference_hash,
    )
    return response
