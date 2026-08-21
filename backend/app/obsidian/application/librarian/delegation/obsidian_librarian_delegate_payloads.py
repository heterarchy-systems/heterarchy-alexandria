"""Delegate status, fallback payload, and answer-merging policy."""

from __future__ import annotations

from app.obsidian.domain.entities.obsidian_note import ObsidianLibrarianWorkflow
from app.shared.types.extra_types import JSONObject


def _delegate_status(
    payload: JSONObject | None,
    response: JSONObject,
) -> str:
    """Normalize delegate execution status for the workflow state."""
    if payload is None:
        status_value = response.get("delegate_status")
        return status_value if isinstance(status_value, str) else "local_only"
    status_value = payload.get("status")
    if isinstance(status_value, str):
        return status_value
    return "delegate_status_unknown"


def _delegate_unavailable_payload(
    workflow: ObsidianLibrarianWorkflow,
    reason: str,
) -> JSONObject:
    """Return a guidance-only delegate result when requested OAuth setup is missing."""
    return {
        "job_id": f"{workflow.thread_id}:delegate-unavailable",
        "status": "GUIDANCE_ONLY",
        "decision": "SUGGEST_HERMES_RESEARCH",
        "librarian_available": False,
        "self_acquisition_allowed": True,
        "recommendation": reason,
        "provider_id": workflow.provider_id,
        "candidate_id": None,
        "librarian_profile_id": workflow.profile_id,
        "librarian_model": None,
        "librarian_role_prompt": None,
        "max_librarian_agents": 1,
        "route_preview": ["GPT OAuth librarian unavailable"],
        "selected_profiles": [],
        "matched_specialties": [],
        "quality_review_added": False,
        "routing_reason": reason,
        "delegates": [],
    }


def _append_delegate_summary(
    response: JSONObject,
    delegate_payload: JSONObject | None,
) -> None:
    """Append delegate summaries to the local answer markdown in-place."""
    if delegate_payload is None:
        return
    summaries: list[str] = []
    delegates = delegate_payload.get("delegates")
    if isinstance(delegates, list):
        for item in delegates:
            if not isinstance(item, dict):
                continue
            summary = item.get("summary")
            if isinstance(summary, str) and summary.strip():
                summaries.append(summary.strip())
    if not summaries:
        recommendation = delegate_payload.get("recommendation")
        if isinstance(recommendation, str) and recommendation.strip():
            summaries.append(recommendation.strip())
    if not summaries:
        return
    answer = str(response.get("answer_markdown") or "")
    response["answer_markdown"] = "\n\n".join(
        [
            answer,
            "## GPT OAuth Librarian",
            "\n\n".join(summaries),
        ]
    )
