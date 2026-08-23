"""SQLAlchemy read models for memory reconciliation audit state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.database import Base
from app.shared.infrastructure.datetime_types import UTCDateTime
from app.shared.infrastructure.identifiers import ID_LENGTH
from app.shared.types.extra_types import JSONValue


class MemoryReconciliationPlanORM(Base):
    """Persisted immutable preview plan with indexed identity fields."""

    __tablename__ = "memory_reconciliation_plans"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    primary_decision: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, JSONValue]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
        ),
        Index(
            "ix_memory_reconciliation_plans_idempotency_key",
            "idempotency_key",
        ),
    )


class MemoryReconciliationResultORM(Base):
    """Persisted auditable result for one apply attempt."""

    __tablename__ = "memory_reconciliation_results"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("memory_reconciliation_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    failure_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    hard_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, JSONValue]] = mapped_column(JSON, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "plan_id",
        ),
        Index(
            "ix_memory_reconciliation_results_plan_id",
            "plan_id",
        ),
    )


class MemoryRelationORM(Base):
    """Indexed directed relationship between two durable Context records."""

    __tablename__ = "memory_relations"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    source_context_id: Mapped[str] = mapped_column(
        String(512), nullable=False, index=True
    )
    target_context_id: Mapped[str] = mapped_column(
        String(512), nullable=False, index=True
    )
    candidate_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decision_source: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, JSONValue]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source_context_id",
            "target_context_id",
            "relation",
            name="uq_memory_relation_identity",
        ),
    )


class MemoryConflictSetORM(Base):
    """Persisted first-class set of unresolved or resolved memory conflicts."""

    __tablename__ = "memory_conflict_sets"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    claim_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    validity_overlap: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, JSONValue]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "claim_key",
            name="uq_memory_conflict_candidate_claim",
        ),
    )


class ContextTemporalStateORM(Base):
    """Temporal and reconciliation overlay for canonical or SQL Context IDs."""

    __tablename__ = "context_temporal_states"

    context_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True, index=True
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True, index=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    payload: Mapped[dict[str, JSONValue]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
