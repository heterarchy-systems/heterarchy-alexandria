"""Memory retrieval and embedding artifact settings."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProviderName,
)
from app.shared.types.configuration_enums import SettingsModule
from app.shared.utils.config import settings_model_config


class EmbeddingConfig(BaseSettings):
    """Explicit embedding provider, model and recovery policy."""

    model_config = settings_model_config(
        env_prefix="SERVICE_", module_name=SettingsModule.MEMORY
    ) | SettingsConfigDict(populate_by_name=True)

    rag_vector_enabled: Annotated[bool, Field(description="RAG vector enabled.")]
    rag_embedding_provider: Annotated[
        EmbeddingProviderName, Field(description="RAG embedding provider.")
    ]
    rag_embedding_model: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="RAG embedding model."),
    ]
    rag_embedding_dimensions: Annotated[
        int, Field(description="RAG embedding dimensions.", ge=1)
    ]
    rag_embedding_cache_dir: Annotated[
        str | None, Field(description="RAG embedding cache directory.")
    ]
    rag_embedding_threads: Annotated[
        int, Field(description="RAG embedding threads.", ge=1, le=32)
    ]
    rag_embedding_recovery_on_startup: Annotated[
        bool, Field(description="RAG embedding recovery on startup.")
    ]
    rag_embedding_recovery_on_vault_reindex: Annotated[
        bool, Field(description="RAG embedding recovery on vault reindex.")
    ]
    rag_embedding_recovery_batch_size: Annotated[
        int, Field(description="RAG embedding recovery batch size.", ge=1, le=1000)
    ]
    rag_embedding_recovery_max_batches: Annotated[
        int, Field(description="RAG embedding recovery maximum batches.", ge=1, le=1000)
    ]


class EmbeddingModelArtifactConfig(BaseSettings):
    """Acquire FastEmbed artifacts using explicit paths and endpoint settings."""

    model_config = settings_model_config(
        env_prefix="SERVICE_RAG_EMBEDDING_", module_name=SettingsModule.MEMORY
    ) | SettingsConfigDict(
        frozen=True,
        hide_input_in_errors=True,
        validate_by_alias=True,
        validate_by_name=True,
        validate_default=True,
    )

    hf_home: Annotated[
        Path | None,
        Field(
            description="Hugging Face cache root, used directly without a hub suffix.",
            validation_alias="HF_HOME",
            repr=False,
        ),
    ]
    fallback_cache_dir: Annotated[
        Path,
        Field(
            description="Fallback FastEmbed cache root.",
            validation_alias="FASTEMBED_CACHE_DIR",
            repr=False,
        ),
    ]
    endpoint: Annotated[
        str,
        Field(
            description="Hugging Face model endpoint.",
            validation_alias="HF_ENDPOINT",
            repr=False,
        ),
    ]
    ort_load_config_from_model: Annotated[
        Literal[0] | None,
        Field(
            description="Reject ONNX Runtime model configuration loading when enabled.",
            validation_alias="ORT_LOAD_CONFIG_FROM_MODEL",
            repr=False,
        ),
    ]
    token_path: Annotated[
        Path,
        Field(
            description="Explicit read-only Hugging Face token file path.", repr=False
        ),
    ]

    @field_validator("endpoint")
    @classmethod
    def normalize_endpoint(cls, value: str) -> str:
        """Validate and normalize an absolute HTTP(S) model endpoint.

        Args:
            value: Configured Hugging Face endpoint.

        Returns:
            Endpoint without trailing path separators.
        """
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        try:
            port = parsed.port
        except ValueError:
            raise ValueError("embedding artifact endpoint is invalid") from None
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (port is not None and port < 1)
            or not normalized
        ):
            raise ValueError("embedding artifact endpoint must be an HTTP(S) origin")
        return normalized

    @field_validator("ort_load_config_from_model", mode="before")
    @classmethod
    def reject_external_ort_model_configuration(
        cls,
        value: object,
    ) -> Literal[0] | None:
        """Allow only unset or explicit zero for the process-wide ORT switch.

        Args:
            value: Raw process environment or constructor value.

        Returns:
            None when unset, otherwise the accepted integer zero.
        """
        if value is None:
            return None
        if type(value) is int and value == 0:
            return 0
        if isinstance(value, str) and value.strip() == "0":
            return 0
        raise ValueError("ORT_LOAD_CONFIG_FROM_MODEL must be unset or 0")
