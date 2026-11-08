"""Feature env-file routing, isolation and precedence contracts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings
from tests.config_test_data import (
    alexandria_api_settings_values,
    app_config_values,
    config_environment_values,
    database_config_values,
    embedding_artifact_config_values,
    embedding_config_values,
    maintenance_queue_config_values,
    mcp_config_values,
    redis_config_values,
    vault_config_values,
)

from app.platform.config.app_config import AppConfig
from app.platform.config.database_config import DatabaseConfig
from app.platform.config.mcp_config import McpApiConfig, McpConfig
from app.platform.config.memory_config import (
    EmbeddingConfig,
    EmbeddingModelArtifactConfig,
)
from app.platform.config.redis_config import MaintenanceQueueConfig, RedisConfig
from app.platform.config.vault_config import VaultConfig

_CASES = (
    (AppConfig, "app", "SERVICE_", app_config_values()),
    (McpConfig, "mcp", "SERVICE_", mcp_config_values()),
    (McpApiConfig, "mcp", "", alexandria_api_settings_values()),
    (EmbeddingConfig, "memory", "SERVICE_", embedding_config_values()),
    (
        EmbeddingModelArtifactConfig,
        "memory",
        "SERVICE_RAG_EMBEDDING_",
        embedding_artifact_config_values(),
    ),
    (VaultConfig, "vault", "SERVICE_", vault_config_values()),
    (DatabaseConfig, "database", "DATABASE_", database_config_values()),
    (RedisConfig, "redis", "SERVICE_REDIS_", redis_config_values()),
    (
        MaintenanceQueueConfig,
        "redis",
        "SERVICE_REDIS_MAINTENANCE_",
        maintenance_queue_config_values(),
    ),
)
_GROUPS = ("app", "mcp", "memory", "vault", "database", "redis")


def _env_values(prefix: str, values: dict[str, object]) -> dict[str, str]:
    if prefix == "":
        return {
            "ALEXANDRIA_API_URL": str(values["base_url"]),
            "ALEXANDRIA_API_TIMEOUT_SECONDS": str(values["timeout"]),
        }
    return config_environment_values(prefix, values)


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8"
    )


@pytest.mark.parametrize(("model", "group", "prefix", "values"), _CASES)
def test_config_reads_its_own_file_after_working_directory_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    model: type[BaseSettings],
    group: str,
    prefix: str,
    values: dict[str, object],
) -> None:
    """Imported models resolve cwd files late and reject unrelated feature sources."""
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.chdir(tmp_path)
    filename = f"{group}_settings.env"
    assert all(Path(path).name == filename for path in model.model_config["env_file"])
    expected = model(_env_file=None, **values)
    own_values = _env_values(prefix, values)
    for sibling in _GROUPS:
        if sibling != group:
            _write_env(
                tmp_path / "module_setting_envs" / f"{sibling}_settings.env",
                dict.fromkeys(own_values, "wrong-feature"),
            )
    _write_env(tmp_path / "module_setting_envs" / filename, own_values)

    assert model().model_dump() == expected.model_dump()


def test_process_environment_overrides_feature_file_with_explicit_null(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Process values win over a complete app file and null remains explicit None."""
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.chdir(tmp_path)
    _write_env(
        tmp_path / "module_setting_envs/app_settings.env",
        config_environment_values("SERVICE_", app_config_values(app_name="from-file")),
    )
    monkeypatch.setenv("SERVICE_APP_NAME", "from-process")
    monkeypatch.setenv("SERVICE_SECRET_ENCRYPTION_KEY", "null")

    config = AppConfig()
    assert config.app_name == "from-process"
    assert config.secret_encryption_key is None


def test_legacy_dotenv_does_not_replace_missing_feature_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Legacy .env and another feature's file cannot satisfy a missing app file."""
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.chdir(tmp_path)
    own_path = tmp_path / "module_setting_envs/app_settings.env"
    monkeypatch.setitem(AppConfig.model_config, "env_file", (own_path,))
    values = config_environment_values("SERVICE_", app_config_values())
    _write_env(tmp_path / ".env", values)
    _write_env(tmp_path / "module_setting_envs/mcp_settings.env", values)

    with pytest.raises(ValidationError):
        AppConfig()


def test_image_provenance_environment_wins_over_local_null_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Mounted app settings cannot replace image-owned revision metadata with null."""
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.chdir(tmp_path)
    _write_env(
        tmp_path / "module_setting_envs/app_settings.env",
        config_environment_values("SERVICE_", app_config_values()),
    )
    monkeypatch.setenv("SERVICE_RUNTIME_REVISION", "image-revision")
    monkeypatch.setenv("SERVICE_RUNTIME_EXPECTED_REVISION", "image-revision")
    monkeypatch.setenv("SERVICE_RUNTIME_BUILD_TIMESTAMP", "image-timestamp")

    config = AppConfig()
    assert config.runtime_revision == "image-revision"
    assert config.runtime_expected_revision == "image-revision"
    assert config.runtime_build_timestamp == "image-timestamp"
