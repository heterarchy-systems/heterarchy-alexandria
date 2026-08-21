"""SQLAlchemy agent profile repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.librarian.domain.contracts.agent_contracts import AgentCreate, AgentUpdate
from app.librarian.domain.entities.read_models import AgentProfile
from app.librarian.domain.event_enum.collaboration_enums import LibrarianProfileRole
from app.librarian.domain.repositories.agent_repository import IAgentRepository
from app.librarian.infrastructure.models.agent_models import AgentProfileORM
from app.shared.exceptions.librarian_exceptions import LibrarianResourceNotFoundError
from app.shared.types.types_convert_utils import aware_utc_datetime


def _to_read_model(row: AgentProfileORM) -> AgentProfile:
    """Map an agent ORM row into the domain read model."""
    return AgentProfile(
        id=row.id,
        name=row.name,
        provider=row.provider,
        description=row.description,
        capabilities=tuple(row.capabilities),
        preferred_librarian_provider=row.preferred_librarian_provider,
        preferred_librarian_model=row.preferred_librarian_model,
        max_librarian_agents=row.max_librarian_agents,
        librarian_role_prompt=row.librarian_role_prompt,
        created_at=aware_utc_datetime(row.created_at),
        updated_at=aware_utc_datetime(row.updated_at),
        librarian_role=LibrarianProfileRole(row.librarian_role),
        librarian_specialties=tuple(row.librarian_specialties or []),
        librarian_routing_priority=row.librarian_routing_priority,
        librarian_enabled=row.librarian_enabled,
    )


class SqlAlchemyAgentRepository(IAgentRepository):
    """Persistence operations for agent profiles."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository.

        Args:
            session: Active async session.
        """
        self._session = session

    async def create(self, payload: AgentCreate) -> AgentProfile:
        """Create an agent profile.

        Args:
            payload [AgentCreate]: Value supplied to create.

        Returns:
            AgentProfile: Value produced by create.
        """
        model = AgentProfileORM(**payload.to_record())
        self._session.add(model)
        await self._session.flush()
        return _to_read_model(model)

    async def get(self, agent_id: str) -> AgentProfile | None:
        """Get one profile by PK.

        Args:
            agent_id [str]: Value supplied to get.

        Returns:
            AgentProfile | None: Value produced by get.
        """
        model = await self._session.get(AgentProfileORM, agent_id)
        return None if model is None else _to_read_model(model)

    async def list_all(self) -> list[AgentProfile]:
        """List all profiles.

        Returns:
            list[AgentProfile]: Value produced by list_all.
        """
        rows = await self._session.execute(select(AgentProfileORM))
        return [_to_read_model(row) for row in rows.scalars().all()]

    async def update(self, agent_id: str, payload: AgentUpdate) -> AgentProfile:
        """Patch profile fields.

        Args:
            agent_id [str]: Value supplied to update.
            payload [AgentUpdate]: Value supplied to update.

        Returns:
            AgentProfile: Value produced by update.
        """
        model = await self._session.get(AgentProfileORM, agent_id)
        if model is None:
            raise LibrarianResourceNotFoundError(f"Agent not found: {agent_id}")

        values = payload.to_record()
        if "name" in values:
            model.name = cast(str, values["name"])
        if "provider" in values:
            model.provider = cast(str, values["provider"])
        if "description" in values:
            model.description = cast(str | None, values["description"])
        if "capabilities" in values:
            model.capabilities = cast(list[str], values["capabilities"])
        if "preferred_librarian_provider" in values:
            model.preferred_librarian_provider = cast(
                str | None,
                values["preferred_librarian_provider"],
            )
        if "preferred_librarian_model" in values:
            model.preferred_librarian_model = cast(
                str | None,
                values["preferred_librarian_model"],
            )
        if "max_librarian_agents" in values:
            model.max_librarian_agents = cast(int, values["max_librarian_agents"])
        if "librarian_role_prompt" in values:
            model.librarian_role_prompt = cast(
                str | None,
                values["librarian_role_prompt"],
            )
        if "librarian_role" in values:
            model.librarian_role = cast(str, values["librarian_role"])
        if "librarian_specialties" in values:
            model.librarian_specialties = cast(
                list[str],
                values["librarian_specialties"],
            )
        if "librarian_routing_priority" in values:
            model.librarian_routing_priority = cast(
                int,
                values["librarian_routing_priority"],
            )
        if "librarian_enabled" in values:
            model.librarian_enabled = cast(bool, values["librarian_enabled"])
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return _to_read_model(model)

    async def delete(self, agent_id: str) -> None:
        """Delete one agent profile.

        Args:
            agent_id [str]: Value supplied to delete.
        """
        model = await self._session.get(AgentProfileORM, agent_id)
        if model is None:
            raise LibrarianResourceNotFoundError(f"Agent not found: {agent_id}")

        await self._session.execute(
            delete(AgentProfileORM).where(AgentProfileORM.id == agent_id)
        )
        await self._session.flush()
