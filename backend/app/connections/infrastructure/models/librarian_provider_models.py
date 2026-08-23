"""ORM model for librarian provider settings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.infrastructure.database import Base
from app.shared.infrastructure.datetime_types import UTCDateTime
from app.shared.infrastructure.identifiers import ID_LENGTH, new_uuid
from app.shared.types.extra_types import JSONObject


class LibrarianProviderORM(Base):
    """Third-party or local provider settings for skill candidate generation."""

    __tablename__ = "librarian_providers"

    id: Mapped[str] = mapped_column(
        String(ID_LENGTH), primary_key=True, default=new_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[JSONObject] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    secrets: Mapped[list[ProviderSecretORM]] = relationship(
        "ProviderSecretORM",
        back_populates="provider",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        """Execute repr.

        Returns:
            str result produced by repr.
        """
        return f"LibrarianProviderORM(id={self.id!r}, name={self.name!r})"


class ProviderSecretORM(Base):
    """Storage abstraction for provider credentials."""

    __tablename__ = "librarian_provider_secrets"

    id: Mapped[str] = mapped_column(
        String(ID_LENGTH), primary_key=True, default=new_uuid
    )
    provider_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("librarian_providers.id", ondelete="CASCADE"),
        index=True,
    )
    key_name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[LibrarianProviderORM] = relationship(
        "LibrarianProviderORM",
        back_populates="secrets",
    )

    def __repr__(self) -> str:
        """Execute repr.

        Returns:
            str result produced by repr.
        """
        return (
            f"ProviderSecretORM(id={self.id!r}, provider_id={self.provider_id!r}, "
            f"key_name={self.key_name!r})"
        )
