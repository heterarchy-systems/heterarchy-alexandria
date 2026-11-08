"""Required embedding configuration contracts."""

from __future__ import annotations

import pytest
from tests.config_test_data import embedding_config_values, set_config_environment

from app.platform.config.memory_config import EmbeddingConfig


def test_embedding_config_reads_explicit_embedding_recovery_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery controls require explicit values and preserve operator overrides."""
    set_config_environment(monkeypatch, "SERVICE_", embedding_config_values())
    monkeypatch.setenv("SERVICE_RAG_EMBEDDING_RECOVERY_ON_STARTUP", "true")
    monkeypatch.setenv("SERVICE_RAG_EMBEDDING_RECOVERY_ON_VAULT_REINDEX", "false")

    config = EmbeddingConfig(_env_file=None)

    assert config.rag_embedding_recovery_on_startup is True
    assert config.rag_embedding_recovery_on_vault_reindex is False
