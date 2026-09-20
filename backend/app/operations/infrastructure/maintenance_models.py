"""SQLAlchemy staging for bounded maintenance job payloads."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.database import Base
from app.shared.infrastructure.datetime_types import UTCDateTime
from app.shared.infrastructure.identifiers import ID_LENGTH
from app.shared.types.extra_types import JSONValue


class MaintenanceJobPayloadORM(Base):
    """Durable payload staging for one asynchronous maintenance job.

    Redis Streams job fields carry identifiers only; the operation bodies
    (for example batch note write operations) live here so the worker can
    execute them and a dead-letter replay can re-execute them idempotently.
    """

    __tablename__ = "maintenance_job_payloads"

    payload_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    body: Mapped[dict[str, JSONValue]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
