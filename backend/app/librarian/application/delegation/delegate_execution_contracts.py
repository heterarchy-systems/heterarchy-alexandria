"""Contracts for planning and executing librarian delegates."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.connections.domain.entities.read_models import LibrarianProvider
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
    LibrarianDelegateResult,
)
from app.librarian.domain.entities.read_models import AgentProfile


@dataclass(frozen=True, slots=True)
class LibrarianProfileResolution:
    """Resolved librarian execution settings for one Hermes request."""

    provider_id: str | None
    librarian_profile_id: str | None
    librarian_model: str | None
    librarian_role_prompt: str | None
    max_librarian_agents: int | None


@dataclass(frozen=True, slots=True)
class LibrarianExecutionPlan:
    """One profile/provider pair that can participate in a response."""

    profile: AgentProfile | None
    provider: LibrarianProvider | None
    resolution: LibrarianProfileResolution
    matched_specialties: tuple[str, ...]


class LibrarianDelegateExecutor(ABC):
    """Boundary for provider-backed delegate execution."""

    @abstractmethod
    async def execute(
        self,
        command: HermesLibrarianAskCommand,
        plan: LibrarianExecutionPlan,
        fallback: LibrarianDelegateResult,
    ) -> LibrarianDelegateResult:
        """Execute one delegate plan with an external provider.

        Args:
            command: Ask-librarian command that carries the prompt.
            plan: Resolved provider/profile execution plan.
            fallback: Safe deterministic delegate result for metadata and fallback.

        Returns:
            LibrarianDelegateResult: Provider-backed delegate result.
        """
