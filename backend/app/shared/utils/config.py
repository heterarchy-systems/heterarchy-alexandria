"""Shared helper for feature-scoped environment-backed settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import SettingsConfigDict

from app.shared.types.configuration_enums import SettingsModule


def settings_model_config(
    env_prefix: str,
    module_name: SettingsModule,
) -> SettingsConfigDict:
    """Build settings config for one feature-owned env file and prefix.

    Args:
        env_prefix: Environment variable prefix such as ``SERVICE_``.
        module_name: Feature settings file name, without the ``_settings.env`` suffix.

    Returns:
        Settings config with ordered checkout and installed-runtime env candidates.
    """
    filename = f"{module_name}_settings.env"
    env_candidates = (
        Path(__file__).resolve().parents[4] / "module_setting_envs" / filename,
        Path("..") / "module_setting_envs" / filename,
        Path("module_setting_envs") / filename,
    )
    return SettingsConfigDict(
        env_prefix=env_prefix,
        env_file=tuple(dict.fromkeys(env_candidates)),
        env_file_encoding="utf-8",
        env_parse_none_str="null",
        extra="ignore",
        hide_input_in_errors=True,
    )
