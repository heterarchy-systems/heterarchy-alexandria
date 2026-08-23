"""Optional Redis cache, queue, and rate-limit settings."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, field_validator
from pydantic_settings import BaseSettings

from app.shared.schemas.common_schemas import described_field
from app.shared.utils.config import settings_model_config


class RedisConfig(BaseSettings):
    """Redis remains removable infrastructure, never canonical storage."""

    model_config = settings_model_config(env_prefix="SERVICE_REDIS_")

    url: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1),
        described_field("URL for this Redis config.", repr=False),
    ] = None
    max_connections: Annotated[
        int, described_field("Max connections for this Redis config.", ge=1, le=64)
    ] = 8

    operational_readiness_ttl_seconds: Annotated[
        int,
        described_field(
            "Operational readiness TTL seconds for this Redis config.", ge=1, le=30
        ),
    ] = 5
    graph_status_ttl_seconds: Annotated[
        int,
        described_field("Graph status TTL seconds for this Redis config.", ge=1, le=30),
    ] = 5
    embedding_health_ttl_seconds: Annotated[
        int,
        described_field(
            "Embedding health TTL seconds for this Redis config.", ge=1, le=60
        ),
    ] = 10

    maintenance_queue_enabled: Annotated[
        bool, described_field("Maintenance queue enabled for this Redis config.")
    ] = True
    maintenance_worker_concurrency: Annotated[
        int,
        described_field(
            "Maintenance worker concurrency for this Redis config.", ge=1, le=4
        ),
    ] = 1
    maintenance_poll_interval_ms: Annotated[
        int,
        described_field(
            "Maintenance poll interval ms for this Redis config.", ge=50, le=5000
        ),
    ] = 250
    maintenance_claim_idle_ms: Annotated[
        int,
        described_field(
            "Maintenance claim idle ms for this Redis config.",
            ge=60000,
            le=24 * 60 * 60 * 1000,
        ),
    ] = 30 * 60 * 1000
    maintenance_job_max_attempts: Annotated[
        int,
        described_field(
            "Maintenance job max attempts for this Redis config.", ge=1, le=10
        ),
    ] = 3
    maintenance_job_status_ttl_seconds: Annotated[
        int,
        described_field(
            "Maintenance job status TTL seconds for this Redis config.",
            ge=60,
            le=7 * 24 * 60 * 60,
        ),
    ] = 24 * 60 * 60
    maintenance_stream_max_length: Annotated[
        int,
        described_field(
            "Maintenance stream max length for this Redis config.", ge=100, le=100000
        ),
    ] = 10000
    maintenance_manual_cooldown_seconds: Annotated[
        int,
        described_field(
            "Maintenance manual cooldown seconds for this Redis config.", ge=1, le=3600
        ),
    ] = 30
    maintenance_scheduler_cooldown_seconds: Annotated[
        int,
        described_field(
            "Maintenance scheduler cooldown seconds for this Redis config.",
            ge=1,
            le=24 * 60 * 60,
        ),
    ] = 5 * 60

    external_api_rate_limit: Annotated[
        int,
        described_field(
            "External API rate limit for this Redis config.", ge=1, le=10000
        ),
    ] = 60
    external_api_rate_window_seconds: Annotated[
        int,
        described_field(
            "External API rate window seconds for this Redis config.", ge=1, le=3600
        ),
    ] = 60

    @field_validator("url", mode="before")
    @classmethod
    def normalize_optional_url(cls, value: str | None) -> str | None:
        """Normalize optional Redis URL text without enabling Redis implicitly.

        Args:
            value: Raw optional Redis URL from the settings boundary.

        Returns:
            Trimmed URL, or None when Redis remains disabled.
        """
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value
