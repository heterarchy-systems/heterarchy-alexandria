"""Handoff packet policies for acquired skill artifacts."""

from __future__ import annotations

from app.librarian.application.skill_artifacts.skill_artifact_validation_policy import (
    _all_evidence_handles,
)
from app.librarian.application.skill_artifacts.skill_artifact_value_policy import (
    _clean_items,
    _evidence_item_payloads,
)
from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
)
from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
)
from app.librarian.domain.event_enum.skill_acquisition_enums import ItemStatus
from app.shared.types.extra_types import JSONObject, JSONValue


def _handoff_payload(
    job: SkillAcquisitionJob,
    artifact: SkillAcquisitionArtifact,
    note_id: str,
    note_path: str,
) -> JSONObject:
    evidence = _evidence_item_payloads(artifact)
    job_payload: JSONObject = {
        "id": job.id,
        "status": "COMPLETED",
        "stage": SkillAcquisitionJobStage.HANDOFF_READY.value,
    }
    skill_payload: JSONObject = {
        "id": note_id,
        "title": artifact.title,
        "path": note_path,
        "status": "draft",
        "review_status": artifact.status.value,
        "version": artifact.version,
        "purpose": artifact.purpose,
        "application_summary": artifact.summary or artifact.purpose,
        "limitations": _skill_limitations(artifact),
    }
    persistence_payload: JSONObject = {
        "saved": True,
        "reindex_status": "succeeded",
        "verified": True,
        "verification_query": artifact.title,
    }
    current_task_payload: JSONObject = {
        "resume_summary": job.task_summary or job.prompt,
        "next_steps": _clean_items(artifact.next_steps),
        "stop_condition": (
            "Stop when the current task has applied the draft skill or when "
            "a prerequisite/tool/risk blocker is found."
        ),
    }
    warnings: list[JSONValue] = _handoff_warnings(artifact)
    payload: JSONObject = {
        "decision": "new_skill_acquired",
        "job": job_payload,
        "progress_summary": (
            "Draft skill artifact saved to Obsidian, refreshed through search, "
            "and verified by exact read-back before completion."
        ),
        "skill": skill_payload,
        "evidence": evidence,
        "persistence": persistence_payload,
        "current_task": current_task_payload,
        "warnings": warnings,
    }
    return payload


def _skill_limitations(artifact: SkillAcquisitionArtifact) -> list[JSONValue]:
    limitations: list[JSONValue] = [
        "draft skill; human review is required before active promotion"
    ]
    if artifact.status is ItemStatus.NEEDS_REVIEW:
        limitations.append("requested_status is needs_review; do not auto-apply")
    if not _all_evidence_handles(artifact):
        limitations.append("claim-linked evidence is missing or insufficient")
    return limitations


def _handoff_warnings(artifact: SkillAcquisitionArtifact) -> list[JSONValue]:
    warnings: list[JSONValue] = []
    if artifact.status is ItemStatus.NEEDS_REVIEW:
        warnings.append(
            {
                "code": "artifact_needs_review",
                "message": (
                    "Evidence or risk review is incomplete; keep the acquired "
                    "skill in needs_review before active use."
                ),
            }
        )
    if not _all_evidence_handles(artifact):
        warnings.append(
            {
                "code": "evidence_insufficient",
                "message": (
                    "No claim-linked evidence was provided; reviewer "
                    "verification is required before active promotion."
                ),
            }
        )
    return warnings
