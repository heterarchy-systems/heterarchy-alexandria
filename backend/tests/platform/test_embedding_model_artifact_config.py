"""Embedding model artifact settings contracts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.platform.config.memory_config import (
    EmbeddingModelArtifactConfig,
)
from tests.config_test_data import (
    embedding_artifact_config_values,
    set_config_environment,
)


def test_artifact_settings_require_every_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """Artifact acquisition requires all paths and endpoint settings explicitly."""
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    with pytest.raises(ValidationError):
        EmbeddingModelArtifactConfig(_env_file=None)


def test_artifact_settings_capture_legacy_environment_aliases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The legacy FastEmbed and Hugging Face environment names remain accepted."""
    hf_home = tmp_path / "hf-home"
    cache_dir = tmp_path / "fastembed-cache"
    set_config_environment(
        monkeypatch,
        "SERVICE_RAG_EMBEDDING_",
        embedding_artifact_config_values(
            hf_home=hf_home,
            fallback_cache_dir=cache_dir,
            endpoint="https://models.example.test/",
            token_path=tmp_path / "token",
        ),
    )
    monkeypatch.setenv("TOKEN_PATH", str(tmp_path / "global-token"))

    config = EmbeddingModelArtifactConfig(_env_file=None)

    assert config.hf_home == hf_home
    assert config.fallback_cache_dir == cache_dir
    assert config.endpoint == "https://models.example.test"
    assert config.token_path == tmp_path / "token"
    assert EmbeddingModelArtifactConfig.model_config["frozen"] is True
    assert EmbeddingModelArtifactConfig.model_config["validate_by_name"] is True
    assert EmbeddingModelArtifactConfig.model_config["validate_by_alias"] is True


def test_token_path_uses_only_the_explicit_service_setting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The generic Hugging Face token path cannot override service configuration."""
    set_config_environment(
        monkeypatch,
        "SERVICE_RAG_EMBEDDING_",
        embedding_artifact_config_values(token_path=tmp_path / "service-token"),
    )
    monkeypatch.setenv("TOKEN_PATH", str(tmp_path / "global-token"))

    config = EmbeddingModelArtifactConfig(_env_file=None)

    assert config.token_path == tmp_path / "service-token"


def test_artifact_settings_keep_explicit_null_and_literal_cache_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit null and empty legacy paths retain their distinct Path semantics."""
    values = embedding_artifact_config_values(hf_home=None)
    config = EmbeddingModelArtifactConfig(_env_file=None, **values)
    assert config.hf_home is None

    empty = EmbeddingModelArtifactConfig(
        _env_file=None,
        **embedding_artifact_config_values(
            hf_home=Path(""), fallback_cache_dir=Path("")
        ),
    )
    assert empty.hf_home == Path("")
    assert empty.fallback_cache_dir == Path("")

    literal = EmbeddingModelArtifactConfig(
        _env_file=None,
        **embedding_artifact_config_values(
            hf_home=Path("~"),
            fallback_cache_dir=Path("  cache root  "),
        ),
    )
    assert literal.hf_home == Path("~")
    assert literal.fallback_cache_dir == Path("  cache root  ")


def test_artifact_settings_accept_python_field_names() -> None:
    """Composition code can provide the typed config fields directly."""
    config = EmbeddingModelArtifactConfig(
        _env_file=None,
        **embedding_artifact_config_values(
            fallback_cache_dir=Path("  literal cache  "),
            token_path=Path("token"),
        ),
    )

    assert config.hf_home is None
    assert config.fallback_cache_dir == Path("  literal cache  ")
    assert config.endpoint == "https://huggingface.co"
    assert config.token_path == Path("token")


def test_artifact_settings_reject_process_wide_ort_model_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ORT model-side configuration remains disabled before provider bootstrap."""
    monkeypatch.delenv("ORT_LOAD_CONFIG_FROM_MODEL", raising=False)
    config = EmbeddingModelArtifactConfig(
        _env_file=None,
        **embedding_artifact_config_values(),
    )
    assert config.ort_load_config_from_model is None

    config_with_override = EmbeddingModelArtifactConfig(
        _env_file=None,
        **embedding_artifact_config_values(ort_load_config_from_model=0),
    )
    assert config_with_override.ort_load_config_from_model == 0


@pytest.mark.parametrize("value", ("1", "true", "false", "2", ""))
def test_artifact_settings_reject_unsupported_ort_model_configuration(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    """The typed process setting rejects enabled and unsupported values unchanged."""
    set_config_environment(
        monkeypatch,
        "SERVICE_RAG_EMBEDDING_",
        embedding_artifact_config_values(),
    )
    monkeypatch.setenv("ORT_LOAD_CONFIG_FROM_MODEL", value)

    with pytest.raises(ValidationError, match="ORT_LOAD_CONFIG_FROM_MODEL"):
        EmbeddingModelArtifactConfig(_env_file=None)

    assert os.environ["ORT_LOAD_CONFIG_FROM_MODEL"] == value


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://user:secret@huggingface.co",
        "https://huggingface.co?token=secret",
        "file:///tmp/models",
    ),
)
def test_artifact_settings_reject_unsafe_or_invalid_endpoints(
    endpoint: str,
) -> None:
    """Endpoint settings cannot embed credentials or switch to a file URL."""
    with pytest.raises(ValidationError) as failure:
        EmbeddingModelArtifactConfig(
            _env_file=None,
            **embedding_artifact_config_values(endpoint=endpoint),
        )
    assert "secret" not in str(failure.value)
