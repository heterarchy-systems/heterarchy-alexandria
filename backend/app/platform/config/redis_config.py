"""Optional Redis cache and rate-limit settings."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.shared.types.configuration_enums import SettingsModule
from app.shared.utils.config import settings_model_config


class RedisConfig(BaseSettings):
    """Redis remains removable infrastructure, never canonical storage."""

    model_config = settings_model_config(
        env_prefix="SERVICE_REDIS_", module_name=SettingsModule.REDIS
    )

    url: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1),
        Field(description="URL for this Redis config.", repr=False),
    ]
    max_connections: Annotated[
        int, Field(description="Max connections for this Redis config.", ge=1, le=64)
    ]

    operational_readiness_ttl_seconds: Annotated[
        int,
        Field(
            description="Operational readiness TTL seconds for this Redis config.",
            ge=1,
            le=30,
        ),
    ]
    graph_status_ttl_seconds: Annotated[
        int,
        Field(
            description="Graph status TTL seconds for this Redis config.", ge=1, le=30
        ),
    ]
    embedding_health_ttl_seconds: Annotated[
        int,
        Field(
            description="Embedding health TTL seconds for this Redis config.",
            ge=1,
            le=60,
        ),
    ]

    external_api_rate_limit: Annotated[
        int,
        Field(
            description="External API rate limit for this Redis config.", ge=1, le=10000
        ),
    ]
    external_api_rate_window_seconds: Annotated[
        int,
        Field(
            description="External API rate window seconds for this Redis config.",
            ge=1,
            le=3600,
        ),
    ]

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


class MaintenanceQueueConfig(BaseSettings):
    """Validated process settings for the Redis maintenance queue."""

    model_config = settings_model_config(
        env_prefix="SERVICE_REDIS_MAINTENANCE_", module_name=SettingsModule.REDIS
    ) | SettingsConfigDict(frozen=True, validate_default=True)

    redis_url: Annotated[
        str | None,
        Field(
            description="Redis URL for this maintenance queue config.",
            validation_alias="SERVICE_REDIS_URL",
            repr=False,
        ),
    ]
    queue_enabled: Annotated[
        bool,
        Field(description="Enable submission and processing of maintenance jobs."),
    ]
    stream_name: str
    dead_letter_stream_name: str
    consumer_group: str
    status_key_prefix: str
    dedup_key_prefix: str
    rate_key_prefix: str
    embedding_threads: Annotated[
        int,
        Field(
            description="Embedding threads for this maintenance queue config.",
            ge=1,
            le=32,
            validation_alias="SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS",
        ),
    ]
    worker_concurrency: Annotated[
        int,
        Field(
            description="Worker concurrency for this maintenance queue config.",
            ge=1,
            le=4,
        ),
    ]
    batch_limit: Annotated[
        int,
        Field(
            description="Batch limit for this maintenance queue config.", ge=1, le=1000
        ),
    ]
    max_attempts: Annotated[
        int,
        Field(
            description="Max attempts for this maintenance queue config.", ge=1, le=10
        ),
    ]
    retry_idle_seconds: Annotated[
        int,
        Field(
            description="Retry idle seconds for this maintenance queue config.",
            ge=1,
            le=3600,
        ),
    ]
    block_milliseconds: Annotated[
        int,
        Field(
            description="Block milliseconds for this maintenance queue config.",
            ge=100,
            le=60000,
        ),
    ]
    status_ttl_seconds: Annotated[
        int,
        Field(
            description="Status TTL seconds for this maintenance queue config.",
            ge=60,
            le=604800,
        ),
    ]
    dedup_cooldown_seconds: Annotated[
        int,
        Field(
            description="Dedup cooldown seconds for this maintenance queue config.",
            ge=1,
            le=3600,
        ),
    ]
    submission_limit: Annotated[
        int,
        Field(
            description="Submission limit for this maintenance queue config.",
            ge=1,
            le=1000,
        ),
    ]
    submission_window_seconds: Annotated[
        int,
        Field(
            description="Submission window seconds for this maintenance queue config.",
            ge=1,
            le=3600,
        ),
    ]
    max_stream_length: Annotated[
        int,
        Field(
            description="Max stream length for this maintenance queue config.",
            ge=100,
            le=1000000,
        ),
    ]
    worker_max_connections: Annotated[
        int,
        Field(
            description="Worker max connections for this maintenance queue config.",
            ge=1,
            le=16,
        ),
    ]

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
