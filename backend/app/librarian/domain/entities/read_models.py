"""Librarian read models returned by repository ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.librarian.domain.event_enum.collaboration_enums import LibrarianProfileRole


@dataclass(slots=True)
class AgentProfile:
    """Read model for a librarian/agent profile."""

    id: str
    name: str
    provider: str
    description: str | None
    capabilities: tuple[str, ...]
    preferred_librarian_provider: str | None
    preferred_librarian_model: str | None
    max_librarian_agents: int
    librarian_role_prompt: str | None
    created_at: datetime
    updated_at: datetime
    librarian_role: LibrarianProfileRole = LibrarianProfileRole.DEFAULT_SEARCH
    librarian_specialties: tuple[str, ...] | None = None
    librarian_routing_priority: int = 100
    librarian_enabled: bool = True

    def __post_init__(self) -> None:
        """Normalize persisted enum values at the read-model boundary."""
        self.librarian_role = LibrarianProfileRole(self.librarian_role)
        self.capabilities = tuple(self.capabilities)
        if self.librarian_specialties is not None:
            self.librarian_specialties = tuple(self.librarian_specialties)
