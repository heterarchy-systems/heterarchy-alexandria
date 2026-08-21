"""Shared usage feedback payload helpers for adapter boundaries."""

from __future__ import annotations

from app.shared.types.extra_types import JSONObject


def usage_feedback_value(
    project: str | None,
    task_summary: str | None,
    feedback: str | None,
) -> JSONObject | str | None:
    """Return usage feedback as plain text or structured adapter payload.

    Args:
        project: Optional project context for the usage event.
        task_summary: Optional task summary context for the usage event.
        feedback: Optional operator feedback text.

    Returns:
        Feedback value accepted by usage-record request schemas.
    """
    if project is None and task_summary is None:
        return feedback
    payload: JSONObject = {}
    if project is not None:
        payload["project"] = project
    if task_summary is not None:
        payload["task_summary"] = task_summary
    if feedback is not None:
        payload["comment"] = feedback
    return payload
