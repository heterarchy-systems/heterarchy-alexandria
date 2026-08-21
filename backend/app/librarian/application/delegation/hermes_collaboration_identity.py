"""Synthetic job identity policy for synchronous Hermes collaboration."""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.librarian.application.delegation.delegate_execution_contracts import (
    LibrarianProfileResolution,
)
from app.librarian.application.routing.profile_routing_contracts import (
    LibrarianRoutingDecision,
)
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
)

_JOB_PREFIX = "librarian-job-"


def collaboration_job_id(
    command: HermesLibrarianAskCommand,
    resolution: LibrarianProfileResolution,
    routing: LibrarianRoutingDecision,
    delegated: bool,
    now: datetime,
) -> str:
    """Return a deterministic-format synthetic job id for one ask response.

    Args:
        command: Original Hermes collaboration command.
        resolution: Representative execution profile resolution.
        routing: Profile routing decision.
        delegated: Whether provider-backed delegation was selected.
        now: Clock value used to distinguish repeated requests.

    Returns:
        Synthetic collaboration job identifier.
    """
    digest = hashlib.sha256(
        (
            f"{command.agent_name}:{command.prompt}:{command.project}:"
            f"{command.task_summary}:{resolution.provider_id}:"
            f"{resolution.librarian_profile_id}:{resolution.librarian_model}:"
            f"{resolution.max_librarian_agents}:{routing.selected_profiles}:"
            f"{routing.matched_specialties}:{delegated}:{now.isoformat()}"
        ).encode()
    ).hexdigest()[:12]
    return f"{_JOB_PREFIX}{digest}"
