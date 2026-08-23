"""Agent profile repository abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.librarian.domain.contracts.agent_contracts import AgentCreate, AgentUpdate
from app.librarian.domain.entities.read_models import AgentProfile


class IAgentRepository(ABC):
    """Persistence contract for agent profile operations."""

    @abstractmethod
    async def create(self, payload: AgentCreate) -> AgentProfile:
        """Create an agent profile.

        Args:
            payload [AgentCreate]: Value supplied to create.

            payload: Validated payload for this operation.
        Returns:
            AgentProfile: Value produced by create.
        """

    @abstractmethod
    async def get(self, agent_id: str) -> AgentProfile | None:
        """Get one agent profile.

        Args:
            agent_id [str]: Value supplied to get.

            agent_id: Identifier for agent.
        Returns:
            AgentProfile | None: Value produced by get.
        """

    @abstractmethod
    async def list_all(self) -> list[AgentProfile]:
        """List all agent profiles.

        Returns:
            list[AgentProfile]: Value produced by list_all.
        """

    @abstractmethod
    async def update(self, agent_id: str, payload: AgentUpdate) -> AgentProfile:
        """Patch profile data.

        Args:
            agent_id [str]: Value supplied to update.
            payload [AgentUpdate]: Value supplied to update.

            agent_id: Identifier for agent.
            payload: Validated payload for this operation.
        Returns:
            AgentProfile: Value produced by update.
        """

    @abstractmethod
    async def delete(self, agent_id: str) -> None:
        """Delete one profile.

        Args:
            agent_id [str]: Value supplied to delete.
            agent_id: Identifier for agent.
        """
