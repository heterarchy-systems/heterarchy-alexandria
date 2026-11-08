"""Strict persisted schemas for newly written maintenance DLQ archives."""

from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.types.extra_types import JSONValue

ARCHIVE_KIND = "maintenance_dlq_retirement"


class ArchivedAttemptSchema(StrictSchemaModel):
    """One required attempt row in a newly written archive."""

    attempt: int
    status: str
    occurred_at: str
    error_summary: str | None


class ArchivedRequestSchema(StrictSchemaModel):
    """Required archived source-request fields."""

    kind: str
    requested_by: str
    source_id: str
    limit: int
    force: bool


class ArchivedJobSchema(StrictSchemaModel):
    """Required archived snapshot fields, including explicit nullable values."""

    job_id: str
    kind: str
    status: str
    requested_by: str
    source_id: str
    limit: int
    force: bool
    attempts: int
    submitted_at: str
    started_at: str | None
    finished_at: str | None
    stream_id: str | None
    error_summary: str | None


class MaintenanceDlqArchiveSchema(StrictSchemaModel):
    """Complete strict wire contract for one newly retired DLQ entry."""

    archive_kind: str
    archive_id: str
    entry_id: str
    job_id: str
    kind: str
    attempts: int
    failed_at: str
    error_summary: str
    source_stream_id: str
    attempt_history: list[ArchivedAttemptSchema]
    source_identity: str
    source_request: ArchivedRequestSchema | None
    source_payload: dict[str, JSONValue] | None
    original_job: ArchivedJobSchema | None
    idempotency_keys: list[str]
    effect_identities: list[str]
    retryable: bool
    outcome_class: str
    recommended_action: str
    error_history: list[str]
    retirement_reason: str
    retirement_classification: str
    retired_by: str
    retired_at: str
