"""Shared helper for building common settings model configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import SettingsConfigDict

_REPOSITORY_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


def settings_model_config(env_prefix: str) -> SettingsConfigDict:
    """Build a shared ``SettingsConfigDict`` based on environment variable prefix.

    Args:
        env_prefix: Environment variable prefix such as ``SERVICE_`` or ``STREAM_``.

    Returns:
        Settings config dictionary that supports loading from ``.env``.
    """
    return SettingsConfigDict(
        env_prefix=env_prefix,
        env_file=(_REPOSITORY_ENV_FILE, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
