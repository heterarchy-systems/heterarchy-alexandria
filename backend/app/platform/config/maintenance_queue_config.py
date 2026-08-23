"""Redis Streams maintenance queue configuration."""

from __future__ import annotations

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.shared.schemas.common_schemas import described_field


class MaintenanceQueueConfig(BaseSettings):
    """Validated process settings for queued embedding maintenance."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SERVICE_REDIS_MAINTENANCE_",
        extra="ignore",
        frozen=True,
        validate_default=True,
    )

    redis_url: Annotated[
        str | None,
        described_field(
            "Redis URL for this maintenance queue config.",
            validation_alias="SERVICE_REDIS_URL",
            repr=False,
        ),
    ] = None
    stream_name: str = "alexandria:maintenance:v1"
    dead_letter_stream_name: str = "alexandria:maintenance:dead:v1"
    consumer_group: str = "alexandria-maintenance-workers-v1"
    status_key_prefix: str = "alexandria:maintenance:job:v1"
    dedup_key_prefix: str = "alexandria:maintenance:dedup:v1"
    rate_key_prefix: str = "alexandria:rate:v1"
    embedding_threads: Annotated[
        int,
        described_field(
            "Embedding threads for this maintenance queue config.",
            ge=1,
            le=32,
            validation_alias="SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS",
        ),
    ] = 1
    worker_concurrency: Annotated[
        int,
        described_field(
            "Worker concurrency for this maintenance queue config.", ge=1, le=4
        ),
    ] = 1
    batch_limit: Annotated[
        int,
        described_field(
            "Batch limit for this maintenance queue config.", ge=1, le=1000
        ),
    ] = 250
    max_attempts: Annotated[
        int,
        described_field("Max attempts for this maintenance queue config.", ge=1, le=10),
    ] = 3
    retry_idle_seconds: Annotated[
        int,
        described_field(
            "Retry idle seconds for this maintenance queue config.", ge=1, le=3600
        ),
    ] = 15
    block_milliseconds: Annotated[
        int,
        described_field(
            "Block milliseconds for this maintenance queue config.", ge=100, le=60000
        ),
    ] = 2000
    status_ttl_seconds: Annotated[
        int,
        described_field(
            "Status TTL seconds for this maintenance queue config.", ge=60, le=604800
        ),
    ] = 86400
    dedup_cooldown_seconds: Annotated[
        int,
        described_field(
            "Dedup cooldown seconds for this maintenance queue config.", ge=1, le=3600
        ),
    ] = 60
    submission_limit: Annotated[
        int,
        described_field(
            "Submission limit for this maintenance queue config.", ge=1, le=1000
        ),
    ] = 6
    submission_window_seconds: Annotated[
        int,
        described_field(
            "Submission window seconds for this maintenance queue config.",
            ge=1,
            le=3600,
        ),
    ] = 60
    max_stream_length: Annotated[
        int,
        described_field(
            "Max stream length for this maintenance queue config.", ge=100, le=1000000
        ),
    ] = 10000
    worker_max_connections: Annotated[
        int,
        described_field(
            "Worker max connections for this maintenance queue config.", ge=1, le=16
        ),
    ] = 2

    @field_validator("redis_url", mode="before")
    @classmethod
    def normalize_optional_redis_url(cls, value: str | None) -> str | None:
        """Normalize an optional Redis URL without enabling Redis implicitly.

        Args:
            value: Raw Redis URL loaded from settings, or None when disabled.

        Returns:
            Trimmed Redis URL, or None for a missing or blank value.
        """
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
