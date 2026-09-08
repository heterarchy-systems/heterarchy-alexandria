"""ORM models for the rebuildable Obsidian index cache."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.database import Base
from app.shared.infrastructure.datetime_types import UTCDateTime
from app.shared.infrastructure.embedding_vector_type import EmbeddingVectorType
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.types.embedding_types import EmbeddingVector
from app.shared.types.extra_types import JSONValue


class ObsidianFileORM(Base):
    """Indexed Obsidian Markdown note metadata."""

    __tablename__ = "obsidian_files"

    note_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    alexandria_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    project: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    frontmatter_json: Mapped[dict[str, JSONValue]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    index_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    modified_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (UniqueConstraint("relative_path", name="uq_obsidian_files_path"),)


class ObsidianChunkORM(Base):
    """Indexed text chunk for one Obsidian note."""

    __tablename__ = "obsidian_chunks"

    id: Mapped[str] = mapped_column(String(255), primary_key=True, default=new_uuid)
    note_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("obsidian_files.note_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        Index(
            "ix_obsidian_chunks_embedding_model_dimensions",
            "embedding_model",
            "embedding_dimensions",
        ),
    )


class ObsidianEdgeORM(Base):
    """Indexed graph edge derived from canonical Markdown."""

    __tablename__ = "obsidian_edges"

    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_note_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("obsidian_files.note_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    target_note_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    target_path: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
