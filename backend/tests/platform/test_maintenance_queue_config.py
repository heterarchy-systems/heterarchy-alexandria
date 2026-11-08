"""Maintenance queue settings contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.config_test_data import (
    config_environment_values,
    maintenance_queue_config_values,
    set_config_environment,
)

from app.platform.config.redis_config import MaintenanceQueueConfig


def test_queue_settings_require_all_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queue must receive every runtime setting explicitly."""
    monkeypatch.delenv("SERVICE_REDIS_MAINTENANCE_QUEUE_ENABLED", raising=False)
    with pytest.raises(ValidationError):
        MaintenanceQueueConfig(_env_file=None)


def test_queue_settings_validate_bounds() -> None:
    """Explicit queue settings retain their bounded operational values."""
    config = MaintenanceQueueConfig(
        _env_file=None,
        **maintenance_queue_config_values(),
    )

    assert config.queue_enabled is True
    assert config.worker_concurrency == 1
    assert config.max_attempts == 3
    assert MaintenanceQueueConfig.model_config["frozen"] is True
    assert MaintenanceQueueConfig.model_config["validate_default"] is True

    with pytest.raises(ValidationError):
        MaintenanceQueueConfig(
            _env_file=None,
            **maintenance_queue_config_values(worker_concurrency=5),
        )


def test_queue_settings_keep_canonical_environment_names_and_hide_redis_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing queue URL, worker and embedding environment contracts remain."""
    values = maintenance_queue_config_values()
    set_config_environment(monkeypatch, "SERVICE_REDIS_MAINTENANCE_", values)
    monkeypatch.setenv("SERVICE_REDIS_MAINTENANCE_QUEUE_ENABLED", "false")
    monkeypatch.setenv("SERVICE_REDIS_MAINTENANCE_WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS", "3")
    monkeypatch.setenv("SERVICE_REDIS_URL", "redis://operator:secret@cache:6379/0")

    config = MaintenanceQueueConfig(_env_file=None)

    assert config.queue_enabled is False
    assert config.worker_concurrency == 2
    assert config.embedding_threads == 3
    assert config.redis_url == "redis://operator:secret@cache:6379/0"
    assert "secret" not in repr(config)


def test_queue_settings_use_current_directory_dotenv_and_process_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The settings model keeps process-over-dotenv precedence for complete input."""
    values = config_environment_values(
        "SERVICE_REDIS_MAINTENANCE_",
        maintenance_queue_config_values(),
    )
    for name in values:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    settings_directory = tmp_path / "module_setting_envs"
    settings_directory.mkdir()
    (settings_directory / "redis_settings.env").write_text(
        "".join(f"{name}={value}\n" for name, value in values.items()),
        encoding="utf-8",
    )

    from_dotenv = MaintenanceQueueConfig()
    monkeypatch.setenv("SERVICE_REDIS_MAINTENANCE_QUEUE_ENABLED", "false")
    from_process_environment = MaintenanceQueueConfig()

    assert from_dotenv.queue_enabled is True
    assert from_process_environment.queue_enabled is False
