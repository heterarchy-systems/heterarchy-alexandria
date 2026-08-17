"""ORM model for external agents consuming the library."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.database import Base
from app.shared.infrastructure.datetime_types import UTCDateTime
from app.shared.infrastructure.identifiers import ID_LENGTH, new_uuid


class AgentProfileORM(Base):
    """Profile record for user/agent identities using heterarchy-alexandria."""

    __tablename__ = "agent_profiles"

    id: Mapped[str] = mapped_column(
        String(ID_LENGTH), primary_key=True, default=new_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    preferred_librarian_provider: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), nullable=True
    )
    preferred_librarian_model: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    max_librarian_agents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    librarian_role_prompt: Mapped[str | None] = mapped_column(
        String(4096), nullable=True
    )
    librarian_role: Mapped[str] = mapped_column(
        String(64), nullable=False, default="DEFAULT_SEARCH"
    )
    librarian_specialties: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    librarian_routing_priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100
    )
    librarian_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    def __repr__(self) -> str:
        return f"AgentProfileORM(id={self.id!r}, name={self.name!r})"
