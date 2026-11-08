"""Obsidian vault and managed note paths."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.shared.types.configuration_enums import SettingsModule
from app.shared.utils.config import settings_model_config


class VaultConfig(BaseSettings):
    """Explicit Obsidian vault and managed-note locations."""

    model_config = settings_model_config(
        env_prefix="SERVICE_", module_name=SettingsModule.VAULT
    ) | SettingsConfigDict(populate_by_name=True)

    obsidian_vault_path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Obsidian vault path."),
    ]
    alexandria_obsidian_root: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Alexandria Obsidian root."),
    ]
    obsidian_vault_config_path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Obsidian vault config path."),
    ]
    memory_compact_note_dir: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Memory compact note directory."),
    ]

    projection_integrity_max_age_seconds: Annotated[
        int,
        Field(
            description="Maximum accepted age of the persisted full projection integrity scan.",
            ge=60,
            le=604800,
        ),
    ]
