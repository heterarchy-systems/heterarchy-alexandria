"""Explicit test inputs for the required environment-backed settings models."""

from __future__ import annotations

from typing import Any

import pytest

_SERVICE_CONFIG_VALUES: dict[str, object] = {
    "app_name": "heterarchy-alexandria",
    "app_env": "local",
    "app_version": "0.1.0",
    "runtime_revision": None,
    "runtime_expected_revision": None,
    "runtime_build_timestamp": None,
    "skill_bundle_root": None,
    "readiness_canary_query": "Alexandria test canary",
    "readiness_canary_limit": 3,
    "projection_integrity_max_age_seconds": 86400,
    "app_log_level": "INFO",
    "secret_encryption_key": None,
    "mcp_transport_host": "0.0.0.0",
    "mcp_auth_mode": "none",
    "mcp_oauth_issuer": None,
    "mcp_oauth_audience": None,
    "mcp_oauth_jwks_url": None,
    "mcp_oauth_resource": None,
    "mcp_oauth_authorization_servers": None,
    "mcp_oauth_required_scope": "alexandria:mcp",
    "mcp_local_approval_key": None,
    "mcp_local_access_token_ttl_seconds": 3600,
    "mcp_local_refresh_token_ttl_seconds": 2592000,
    "mcp_local_authorization_code_ttl_seconds": 300,
    "mcp_local_approval_ttl_seconds": 600,
    "mcp_local_pairing_code_ttl_seconds": 300,
    "mcp_local_max_approval_attempts": 5,
    "rag_vector_enabled": True,
    "rag_embedding_provider": "fastembed",
    "rag_embedding_model": "intfloat/multilingual-e5-small",
    "rag_embedding_dimensions": 384,
    "rag_embedding_cache_dir": None,
    "rag_embedding_threads": 4,
    "rag_embedding_recovery_on_startup": False,
    "rag_embedding_recovery_on_vault_reindex": False,
    "rag_embedding_recovery_batch_size": 250,
    "rag_embedding_recovery_max_batches": 40,
    "obsidian_vault_path": "./data/test-vault",
    "alexandria_obsidian_root": "Alexandria",
    "obsidian_vault_config_path": "./data/test-vault-config.json",
    "memory_compact_note_dir": "Alexandria/Memory Compacts",
}

_REDIS_CONFIG_VALUES: dict[str, object] = {
    "url": None,
    "max_connections": 8,
    "operational_readiness_ttl_seconds": 5,
    "graph_status_ttl_seconds": 5,
    "embedding_health_ttl_seconds": 10,
    "external_api_rate_limit": 60,
    "external_api_rate_window_seconds": 60,
}

_MAINTENANCE_QUEUE_CONFIG_VALUES: dict[str, object] = {
    "redis_url": None,
    "queue_enabled": True,
    "stream_name": "alexandria:maintenance:v1",
    "dead_letter_stream_name": "alexandria:maintenance:dead:v1",
    "consumer_group": "alexandria-maintenance-workers-v1",
    "status_key_prefix": "alexandria:maintenance:job:v1",
    "dedup_key_prefix": "alexandria:maintenance:dedup:v1",
    "rate_key_prefix": "alexandria:rate:v1",
    "embedding_threads": 1,
    "worker_concurrency": 1,
    "batch_limit": 250,
    "max_attempts": 3,
    "retry_idle_seconds": 15,
    "block_milliseconds": 2000,
    "status_ttl_seconds": 86400,
    "dedup_cooldown_seconds": 60,
    "submission_limit": 6,
    "submission_window_seconds": 60,
    "max_stream_length": 10000,
    "worker_max_connections": 2,
}


def service_config_values(**overrides: object) -> dict[str, object]:
    """Return the explicit environment profile used by backend tests."""
    return _SERVICE_CONFIG_VALUES | overrides


def _feature_values(
    names: tuple[str, ...], overrides: dict[str, object]
) -> dict[str, object]:
    return {name: _SERVICE_CONFIG_VALUES[name] for name in names} | overrides


def app_config_values(**overrides: object) -> dict[str, object]:
    """Return explicit application identity and logging values."""
    return _feature_values(
        (
            "app_name",
            "app_env",
            "app_version",
            "app_log_level",
            "runtime_revision",
            "runtime_expected_revision",
            "runtime_build_timestamp",
            "secret_encryption_key",
            "skill_bundle_root",
            "readiness_canary_query",
            "readiness_canary_limit",
        ),
        overrides,
    )


def mcp_config_values(**overrides: object) -> dict[str, object]:
    """Return explicit MCP authentication and transport values."""
    return _feature_values(
        tuple(name for name in _SERVICE_CONFIG_VALUES if name.startswith("mcp_")),
        overrides,
    )


def embedding_config_values(**overrides: object) -> dict[str, object]:
    """Return explicit retrieval and embedding recovery values."""
    return _feature_values(
        tuple(name for name in _SERVICE_CONFIG_VALUES if name.startswith("rag_")),
        overrides,
    )


def vault_config_values(**overrides: object) -> dict[str, object]:
    """Return explicit Vault paths."""
    return _feature_values(
        (
            "obsidian_vault_path",
            "alexandria_obsidian_root",
            "obsidian_vault_config_path",
            "memory_compact_note_dir",
            "projection_integrity_max_age_seconds",
        ),
        overrides,
    )


def database_config_values(**overrides: object) -> dict[str, object]:
    """Return explicit valid inputs for the database settings model."""
    return {
        "url": "postgresql+asyncpg://alexandria:alexandria@localhost:5432/alexandria"
    } | overrides


def embedding_artifact_config_values(**overrides: object) -> dict[str, object]:
    """Return explicit valid inputs for FastEmbed artifact settings."""
    from pathlib import Path

    return {
        "hf_home": None,
        "fallback_cache_dir": Path(".fastembed_cache"),
        "endpoint": "https://huggingface.co",
        "ort_load_config_from_model": None,
        "token_path": Path.home() / ".cache/huggingface/token",
    } | overrides


def alexandria_api_settings_values(**overrides: object) -> dict[str, object]:
    """Return explicit valid inputs for the MCP API client settings."""
    return {"base_url": "http://localhost:8000", "timeout": 30.0} | overrides


def redis_config_values(**overrides: object) -> dict[str, object]:
    """Return explicit valid inputs for the complete Redis settings model."""
    return _REDIS_CONFIG_VALUES | overrides


def maintenance_queue_config_values(**overrides: object) -> dict[str, object]:
    """Return explicit valid inputs using declared queue validation aliases."""
    values = _MAINTENANCE_QUEUE_CONFIG_VALUES | overrides
    values["SERVICE_REDIS_URL"] = values.pop("redis_url")
    values["SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS"] = values.pop(
        "embedding_threads"
    )
    return values


def config_environment_values(
    prefix: str,
    values: dict[str, object],
) -> dict[str, str]:
    """Return canonical environment names and explicit encoded values."""
    aliases = {
        ("SERVICE_RAG_EMBEDDING_", "hf_home"): "HF_HOME",
        ("SERVICE_RAG_EMBEDDING_", "fallback_cache_dir"): "FASTEMBED_CACHE_DIR",
        ("SERVICE_RAG_EMBEDDING_", "endpoint"): "HF_ENDPOINT",
        (
            "SERVICE_RAG_EMBEDDING_",
            "ort_load_config_from_model",
        ): "ORT_LOAD_CONFIG_FROM_MODEL",
        ("SERVICE_REDIS_MAINTENANCE_", "redis_url"): "SERVICE_REDIS_URL",
        (
            "SERVICE_REDIS_MAINTENANCE_",
            "embedding_threads",
        ): "SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS",
        ("SERVICE_REDIS_MAINTENANCE_", "SERVICE_REDIS_URL"): "SERVICE_REDIS_URL",
        (
            "SERVICE_REDIS_MAINTENANCE_",
            "SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS",
        ): "SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS",
    }
    return {
        aliases.get((prefix, name), f"{prefix}{name.upper()}"): (
            "null" if value is None else str(value)
        )
        for name, value in values.items()
    }


def set_config_environment(
    monkeypatch: Any,
    prefix: str,
    values: dict[str, object],
) -> None:
    """Set every settings field through its canonical uppercase env name."""
    for name, value in config_environment_values(prefix, values).items():
        monkeypatch.setenv(name, value)


def application_container(**overrides: object) -> Any:
    """Build an isolated test container with explicit feature configuration."""
    import os

    from dependency_injector import providers

    from app.container import ApplicationContainer
    from app.platform.config.app_config import AppConfig
    from app.platform.config.database_config import DatabaseConfig
    from app.platform.config.mcp_config import McpApiConfig, McpConfig
    from app.platform.config.memory_config import EmbeddingConfig
    from app.platform.config.redis_config import MaintenanceQueueConfig, RedisConfig
    from app.platform.config.vault_config import VaultConfig

    unknown = set(overrides) - _SERVICE_CONFIG_VALUES.keys()
    if unknown:
        raise ValueError(f"Unknown test configuration: {sorted(unknown)}")
    container = ApplicationContainer()
    models = (
        ("app_config", AppConfig, app_config_values()),
        ("mcp_config", McpConfig, mcp_config_values()),
        ("embedding_config", EmbeddingConfig, embedding_config_values()),
        ("vault_config", VaultConfig, vault_config_values()),
        ("mcp_api_config", McpApiConfig, alexandria_api_settings_values()),
        (
            "database_config",
            DatabaseConfig,
            database_config_values(
                url=os.environ.get(
                    "DATABASE_URL", "postgresql+asyncpg://test@localhost:5432/test"
                )
            ),
        ),
        ("redis_config", RedisConfig, redis_config_values()),
        (
            "maintenance_queue_config",
            MaintenanceQueueConfig,
            maintenance_queue_config_values(),
        ),
    )
    for name, model, values in models:
        selected = {key: value for key, value in overrides.items() if key in values}
        container.providers[name].override(
            providers.Object(model(_env_file=None, **(values | selected)))
        )
    return container


@pytest.fixture
def maintenance_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply explicit worker inputs when Redis tests run without the DB test profile."""
    set_config_environment(
        monkeypatch, "SERVICE_REDIS_MAINTENANCE_", maintenance_queue_config_values()
    )
    set_config_environment(monkeypatch, "SERVICE_", embedding_config_values())
