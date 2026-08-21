"""Database configuration model."""

from __future__ import annotations

from typing import Annotated

from app.shared.schemas.common_schemas import described_field
from app.shared.utils.config import settings_model_config
from pydantic import field_validator
from pydantic_settings import BaseSettings


class DatabaseConfig(BaseSettings):
    """Database runtime settings for SQLAlchemy persistence."""

    model_config = settings_model_config(env_prefix="DATABASE_")

    url: Annotated[str, described_field("Async SQLAlchemy database URL.")] = (
        "postgresql+asyncpg://alexandria:alexandria@localhost:5432/alexandria_hermes"
    )

    @field_validator("url")
    @classmethod
    def normalize_async_database_url(cls, value: str) -> str:
        """Normalize generic PostgreSQL URLs to the configured async driver.

        Args:
            value: Raw database URL from the settings boundary.

        Returns:
            Normalized asynchronous SQLAlchemy URL.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("database URL must not be blank")
        for prefix in ("postgresql://", "postgres://"):
            if normalized.startswith(prefix):
                normalized = "postgresql+asyncpg://" + normalized.removeprefix(prefix)
                break
        if not normalized.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "heterarchy-alexandria runtime requires PostgreSQL via asyncpg"
            )
        return normalized
