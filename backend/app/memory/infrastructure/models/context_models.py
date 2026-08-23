"""ORM models for Context Vault storage."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.memory.domain.event_enum.context_enums import (
    ContextAccessActorType,
    ContextAccessMethod,
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
)
from app.shared.infrastructure.database import Base
from app.shared.infrastructure.datetime_types import UTCDateTime
from app.shared.infrastructure.embedding_vector_type import EmbeddingVectorType
from app.shared.infrastructure.identifiers import ID_LENGTH, new_uuid
from app.shared.types.embedding_types import EmbeddingVector
from app.shared.types.extra_types import JSONValue


def _enum_values_sql(values: tuple[str, ...]) -> str:
    """Execute enum values sql.

    Args:
        values: Values being processed.

    Returns:
        str result produced by enum values sql.
    """
    return ",".join(f"'{value}'" for value in values)


class ContextORM(Base):
    """Stored durable context row."""

    __tablename__ = "contexts"

    id: Mapped[str] = mapped_column(
        String(ID_LENGTH), primary_key=True, default=new_uuid
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_format: Mapped[str] = mapped_column(String(24), nullable=False)
    project: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContextScope.PROJECT.value, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True, index=True
    )
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContextScope.PROJECT.value, index=True
    )
    source_agent: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    importance: Mapped[str] = mapped_column(String(16), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    restore_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_metadata: Mapped[dict[str, JSONValue]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint(
            f"kind IN ({_enum_values_sql(tuple(item.value for item in ContextKind))})",
            name="ck_contexts_kind",
        ),
        CheckConstraint(
            "content_format IN "
            f"({_enum_values_sql(tuple(item.value for item in ContextContentFormat))})",
            name="ck_contexts_content_format",
        ),
        CheckConstraint(
            "source_type IN "
            f"({_enum_values_sql(tuple(item.value for item in ContextSourceType))})",
            name="ck_contexts_source_type",
        ),
        CheckConstraint(
            f"scope IN ({_enum_values_sql(tuple(item.value for item in ContextScope))})",
            name="ck_contexts_scope",
        ),
        CheckConstraint(
            "visibility IN "
            f"({_enum_values_sql(tuple(item.value for item in ContextScope))})",
            name="ck_contexts_visibility",
        ),
        CheckConstraint(
            "importance IN "
            f"({_enum_values_sql(tuple(item.value for item in ContextImportance))})",
            name="ck_contexts_importance",
        ),
        CheckConstraint(
            "status IN "
            f"({_enum_values_sql(tuple(item.value for item in ContextStorageStatus))})",
            name="ck_contexts_status",
        ),
    )


class ContextChunkORM(Base):
    """Searchable chunk for one context."""

    __tablename__ = "context_chunks"

    id: Mapped[str] = mapped_column(
        String(ID_LENGTH), primary_key=True, default=new_uuid
    )
    context_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("contexts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[EmbeddingVector | None] = mapped_column(
        EmbeddingVectorType(), nullable=True
    )
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_provider_version: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    embedding_pooling_mode: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    embedding_normalize: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    embedding_fingerprint_key: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, index=True
    )
    embedding_fingerprint_json: Mapped[dict[str, JSONValue] | None] = mapped_column(
        "embedding_fingerprint", JSON, nullable=True
    )
    embedding_indexed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    chunk_metadata: Mapped[dict[str, JSONValue]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ContextAccessEventORM(Base):
    """Audit event for recent Context Vault views/recall accesses."""

    __tablename__ = "context_access_events"

    id: Mapped[str] = mapped_column(
        String(ID_LENGTH), primary_key=True, default=new_uuid
    )
    context_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("contexts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    accessed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, index=True
    )
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    access_method: Mapped[str] = mapped_column(String(32), nullable=False)
    source_surface: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "actor_type IN "
            f"({_enum_values_sql(tuple(item.value for item in ContextAccessActorType))})",
            name="ck_context_access_events_actor_type",
        ),
        CheckConstraint(
            "access_method IN "
            f"({_enum_values_sql(tuple(item.value for item in ContextAccessMethod))})",
            name="ck_context_access_events_access_method",
        ),
    )
