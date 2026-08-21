"""Value policies for durable skill-acquisition jobs."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime

from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
)
from app.shared.types.extra_types import JSONObject
from app.shared.utils.logging import redact_sensitive_text

_JOB_PREFIX = "skill-acquisition-"
_LEGACY_DIRECT_START_OVERRIDE = (
    "Direct skill-acquisition start without a search-first snapshot; "
    "recorded for compatibility with legacy callers."
)


def _search_snapshot_unavailable(search_snapshot: JSONObject | None) -> bool:
    if search_snapshot is None:
        return False
    if search_snapshot.get("decision") == "SEARCH_UNAVAILABLE":
        return True
    handoff = search_snapshot.get("handoff")
    if isinstance(handoff, dict):
        return handoff.get("decision") == "skill_search_repair_required"
    return False


def _search_snapshot_sufficient(search_snapshot: JSONObject | None) -> bool:
    if search_snapshot is None:
        return False
    return search_snapshot.get("decision") == "FOUND_SUFFICIENT"


def _job_id(prompt: str, agent_name: str, now: datetime) -> str:
    digest = hashlib.sha256(
        f"{agent_name}:{prompt}:{now.isoformat()}".encode()
    ).hexdigest()
    return f"{_JOB_PREFIX}{digest[:18]}"


def _completion_summary(
    artifact: SkillAcquisitionArtifact,
) -> str:
    if artifact.source_summary is not None and artifact.source_summary.strip():
        return artifact.source_summary.strip()
    return f"Acquired skill artifact generated: {artifact.title}"


def _clean_items(values: Sequence[str]) -> list[str]:
    return [value.strip() for value in values if value.strip()]


def _redact_secret_text(value: str | None) -> str | None:
    if value is None:
        return None
    return redact_sensitive_text(value)


def _override_reason(
    search_snapshot: JSONObject | None,
    acquisition_override_reason: str | None,
) -> str | None:
    if search_snapshot is not None:
        return None
    if acquisition_override_reason is not None and acquisition_override_reason.strip():
        return acquisition_override_reason.strip()
    return _LEGACY_DIRECT_START_OVERRIDE
