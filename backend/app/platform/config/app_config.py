"""Application identity and process metadata settings."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.shared.types.configuration_enums import SettingsModule
from app.shared.utils.config import settings_model_config


class AppConfig(BaseSettings):
    """Explicit application identity and build provenance."""

    model_config = settings_model_config(
        env_prefix="SERVICE_", module_name=SettingsModule.APP
    ) | SettingsConfigDict(populate_by_name=True)

    app_name: Annotated[str, Field(description="Application name.")]
    app_env: Annotated[
        Literal["local", "stage", "prod"], Field(description="Application environment.")
    ]
    app_version: Annotated[str, Field(description="Application version.")]
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    runtime_revision: Annotated[
        str | None,
        Field(description="Source revision baked into the running application image."),
    ]
    runtime_expected_revision: Annotated[
        str | None,
        Field(
            description="Deployment revision expected by the runtime environment for drift detection."
        ),
    ]
    runtime_build_timestamp: Annotated[
        str | None,
        Field(description="Build timestamp baked into the running application image."),
    ]
    secret_encryption_key: Annotated[
        str | None,
        Field(description="Secret encryption key for this app config.", repr=False),
    ]
    skill_bundle_root: Annotated[
        str | None,
        Field(
            description="Optional skill bundle root override for skill contract checks."
        ),
    ]
    readiness_canary_query: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=500),
        Field(
            description="Bounded query used by operational retrieval readiness canaries."
        ),
    ]
    readiness_canary_limit: Annotated[
        int,
        Field(
            description="Result limit used by operational retrieval readiness canaries.",
            ge=3,
            le=10,
        ),
    ]
