"""Agent repository command contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.librarian.domain.event_enum.collaboration_enums import LibrarianProfileRole
from app.librarian.domain.types.agent_payload_types import (
    AgentCreateRecord,
    AgentUpdateRecord,
    AgentUpdateValues,
)


@dataclass(slots=True, kw_only=True)
class AgentCreate:
    """Fields required to persist an agent profile."""

    name: str
    provider: str
    description: str | None
    capabilities: tuple[str, ...]
    preferred_librarian_provider: str | None
    preferred_librarian_model: str | None
    max_librarian_agents: int
    librarian_role_prompt: str | None
    librarian_role: LibrarianProfileRole
    librarian_specialties: tuple[str, ...]
    librarian_routing_priority: int
    librarian_enabled: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Normalize profile collections to immutable values."""
        self.capabilities = tuple(self.capabilities)
        self.librarian_specialties = tuple(self.librarian_specialties)

    def to_record(self) -> AgentCreateRecord:
        """Return persistence fields for SQLAlchemy model construction.

        Returns:
            AgentCreateRecord: Persistence record for agent creation.
        """
        record = AgentCreateRecord(
            name=self.name,
            provider=self.provider,
            description=self.description,
            capabilities=list(self.capabilities),
            preferred_librarian_provider=self.preferred_librarian_provider,
            preferred_librarian_model=self.preferred_librarian_model,
            max_librarian_agents=self.max_librarian_agents,
            librarian_role_prompt=self.librarian_role_prompt,
            librarian_role=self.librarian_role.value,
            librarian_specialties=list(self.librarian_specialties),
            librarian_routing_priority=self.librarian_routing_priority,
            librarian_enabled=self.librarian_enabled,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
        return record


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentUpdate:
    """Patch fields for an agent profile."""

    values: AgentUpdateValues

    def to_record(self) -> AgentUpdateRecord:
        """Return persistence fields for patching.

        Returns:
            AgentUpdateRecord: Persistence values for agent patching.
        """
        record: AgentUpdateRecord = {}
        if "name" in self.values:
            record["name"] = self.values["name"]
        if "provider" in self.values:
            record["provider"] = self.values["provider"]
        if "description" in self.values:
            record["description"] = self.values["description"]
        if "capabilities" in self.values:
            record["capabilities"] = self.values["capabilities"]
        if "preferred_librarian_provider" in self.values:
            record["preferred_librarian_provider"] = self.values[
                "preferred_librarian_provider"
            ]
        if "preferred_librarian_model" in self.values:
            record["preferred_librarian_model"] = self.values[
                "preferred_librarian_model"
            ]
        if "max_librarian_agents" in self.values:
            record["max_librarian_agents"] = self.values["max_librarian_agents"]
        if "librarian_role_prompt" in self.values:
            record["librarian_role_prompt"] = self.values["librarian_role_prompt"]
        if "librarian_role" in self.values:
            record["librarian_role"] = self.values["librarian_role"].value
        if "librarian_specialties" in self.values:
            record["librarian_specialties"] = self.values["librarian_specialties"]
        if "librarian_routing_priority" in self.values:
            record["librarian_routing_priority"] = self.values[
                "librarian_routing_priority"
            ]
        if "librarian_enabled" in self.values:
            record["librarian_enabled"] = self.values["librarian_enabled"]
        return record
