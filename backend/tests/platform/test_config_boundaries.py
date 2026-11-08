"""Independent, required feature configuration boundaries."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError
from tests.config_test_data import (
    app_config_values,
    embedding_config_values,
    mcp_config_values,
    service_config_values,
    vault_config_values,
)

from app.platform.config.app_config import AppConfig
from app.platform.config.memory_config import EmbeddingConfig
from app.platform.config.mcp_config import McpConfig
from app.platform.config.vault_config import VaultConfig

_FEATURES = (
    (AppConfig, app_config_values()),
    (McpConfig, mcp_config_values()),
    (EmbeddingConfig, embedding_config_values()),
    (VaultConfig, vault_config_values()),
)


def test_feature_configs_partition_existing_environment_contract() -> None:
    """Each former service field has exactly one owner and requires explicit input."""
    owners: set[str] = set()
    for model, values in _FEATURES:
        fields = model.model_fields
        assert set(fields) == set(values)
        assert not owners.intersection(fields)
        assert all(
            field.is_required() and field.default_factory is None
            for field in fields.values()
        )
        owners.update(fields)
    assert owners == set(service_config_values())
    assert len(AppConfig.model_fields) == 11
    assert len(owners) == 41


@pytest.mark.parametrize(("model", "values"), _FEATURES)
def test_feature_config_loads_independently_and_rejects_each_missing_field(
    monkeypatch: pytest.MonkeyPatch,
    model: type[AppConfig | McpConfig | EmbeddingConfig | VaultConfig],
    values: dict[str, object],
) -> None:
    """A feature can load without sibling settings but cannot omit its own inputs."""
    monkeypatch.setattr(os, "environ", {})
    config = model(_env_file=None, **values)
    assert set(config.model_dump()) == set(values)
    for name in values:
        remaining = {key: value for key, value in values.items() if key != name}
        with pytest.raises(ValidationError) as failure:
            model(_env_file=None, **remaining)
        errors = failure.value.errors()
        assert len(errors) == 1
        assert errors[0]["type"] == "missing"
