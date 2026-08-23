"""Environment-backed field declarations for the application settings boundary."""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import AliasChoices, SecretStr, StringConstraints
from pydantic_settings import BaseSettings

from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.memory.application.retrieval.embeddings.embedding_contract import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_THREADS,
)
from app.memory.application.retrieval.embeddings.embedding_factory import (
    EmbeddingProviderName,
)
from app.shared.schemas.common_schemas import described_field
from app.shared.utils.config import settings_model_config

DEFAULT_CODEX_OAUTH_ISSUER: Final[str] = "https://auth.openai.com"
DEFAULT_CODEX_OAUTH_CLIENT_ID: Final[str] = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_CODEX_OAUTH_DEVICE_EXPIRES_IN_SECONDS: Final[int] = 900
DEFAULT_CODEX_OAUTH_MIN_POLL_INTERVAL_SECONDS: Final[int] = 3
DEFAULT_MEMORY_RECONCILIATION_MODEL: Final[str] = "gpt-5.5"
DEFAULT_MEMORY_RECONCILIATION_PROVIDER_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_MCP_LOCAL_ACCESS_TOKEN_TTL_SECONDS: Final[int] = 60 * 60
DEFAULT_MCP_LOCAL_REFRESH_TOKEN_TTL_SECONDS: Final[int] = 30 * 24 * 60 * 60
DEFAULT_MCP_LOCAL_AUTHORIZATION_CODE_TTL_SECONDS: Final[int] = 5 * 60
DEFAULT_MCP_LOCAL_APPROVAL_TTL_SECONDS: Final[int] = 10 * 60
DEFAULT_MCP_LOCAL_PAIRING_CODE_TTL_SECONDS: Final[int] = 5 * 60
DEFAULT_MCP_LOCAL_MAX_APPROVAL_ATTEMPTS: Final[int] = 5
_LOCAL_HTTP_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1"})


class AppConfigFields(BaseSettings):
    """Typed environment fields inherited by the validated AppConfig boundary."""

    model_config = {
        **settings_model_config(env_prefix="SERVICE_"),
        "populate_by_name": True,
    }
    app_name: Annotated[str, described_field("App name for this app config.")] = (
        "heterarchy-alexandria"
    )
    app_env: Annotated[
        Literal["local", "stage", "prod"],
        described_field("App env for this app config."),
    ] = "local"
    app_version: Annotated[str, described_field("App version for this app config.")] = (
        "0.1.0"
    )
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    secret_encryption_key: Annotated[
        str | None, described_field("Secret encryption key for this app config.")
    ] = None
    mcp_transport_host: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("MCP transport host for this app config."),
    ] = "0.0.0.0"
    mcp_auth_mode: Annotated[
        McpAuthMode, described_field("MCP auth mode for this app config.")
    ] = McpAuthMode.NONE
    mcp_oauth_issuer: Annotated[
        str | None, described_field("MCP OAuth issuer for this app config.")
    ] = None
    mcp_oauth_audience: Annotated[
        str | None, described_field("MCP OAuth audience for this app config.")
    ] = None
    mcp_oauth_jwks_url: Annotated[
        str | None, described_field("MCP OAuth jwks URL for this app config.")
    ] = None
    mcp_oauth_resource: Annotated[
        str | None, described_field("MCP OAuth resource for this app config.")
    ] = None
    mcp_oauth_authorization_servers: Annotated[
        str | None,
        described_field("MCP OAuth authorization servers for this app config."),
    ] = None
    mcp_oauth_required_scope: Annotated[
        str, described_field("MCP OAuth required scope for this app config.")
    ] = "alexandria:mcp"
    mcp_local_approval_key: Annotated[
        SecretStr | None,
        described_field(
            "MCP local approval key for this app config.",
            validation_alias=AliasChoices(
                "SERVICE_MCP_LOCAL_APPROVAL_KEY", "ALEXANDRIA_OPERATOR_API_KEY"
            ),
            repr=False,
        ),
    ] = None
    mcp_local_access_token_ttl_seconds: Annotated[
        int,
        described_field(
            "MCP local access token TTL seconds for this app config.",
            ge=5 * 60,
            le=24 * 60 * 60,
        ),
    ] = DEFAULT_MCP_LOCAL_ACCESS_TOKEN_TTL_SECONDS
    mcp_local_refresh_token_ttl_seconds: Annotated[
        int,
        described_field(
            "MCP local refresh token TTL seconds for this app config.",
            ge=24 * 60 * 60,
            le=365 * 24 * 60 * 60,
        ),
    ] = DEFAULT_MCP_LOCAL_REFRESH_TOKEN_TTL_SECONDS
    mcp_local_authorization_code_ttl_seconds: Annotated[
        int,
        described_field(
            "MCP local authorization code TTL seconds for this app config.",
            ge=60,
            le=10 * 60,
        ),
    ] = DEFAULT_MCP_LOCAL_AUTHORIZATION_CODE_TTL_SECONDS
    mcp_local_approval_ttl_seconds: Annotated[
        int,
        described_field(
            "MCP local approval TTL seconds for this app config.", ge=60, le=30 * 60
        ),
    ] = DEFAULT_MCP_LOCAL_APPROVAL_TTL_SECONDS
    mcp_local_pairing_code_ttl_seconds: Annotated[
        int,
        described_field(
            "MCP local pairing code TTL seconds for this app config.", ge=60, le=10 * 60
        ),
    ] = DEFAULT_MCP_LOCAL_PAIRING_CODE_TTL_SECONDS
    mcp_local_max_approval_attempts: Annotated[
        int,
        described_field(
            "MCP local max approval attempts for this app config.", ge=1, le=10
        ),
    ] = DEFAULT_MCP_LOCAL_MAX_APPROVAL_ATTEMPTS
    codex_oauth_issuer: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Codex OAuth issuer for this app config."),
    ] = DEFAULT_CODEX_OAUTH_ISSUER
    codex_oauth_client_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Codex oauth client identifier for this app config."),
    ] = DEFAULT_CODEX_OAUTH_CLIENT_ID
    codex_oauth_device_expires_in_seconds: Annotated[
        int,
        described_field(
            "Codex OAuth device expires in seconds for this app config.",
            ge=60,
            le=60 * 60,
        ),
    ] = DEFAULT_CODEX_OAUTH_DEVICE_EXPIRES_IN_SECONDS
    codex_oauth_min_poll_interval_seconds: Annotated[
        int,
        described_field(
            "Codex OAuth min poll interval seconds for this app config.", ge=1, le=60
        ),
    ] = DEFAULT_CODEX_OAUTH_MIN_POLL_INTERVAL_SECONDS
    memory_reconciliation_provider_id: Annotated[
        str | None,
        described_field(
            "Memory reconciliation provider identifier for this app config."
        ),
    ] = None
    memory_reconciliation_model: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Memory reconciliation model for this app config."),
    ] = DEFAULT_MEMORY_RECONCILIATION_MODEL
    memory_reconciliation_provider_timeout_seconds: Annotated[
        float,
        described_field(
            "Memory reconciliation provider timeout seconds for this app config.",
            gt=0,
            le=300,
        ),
    ] = DEFAULT_MEMORY_RECONCILIATION_PROVIDER_TIMEOUT_SECONDS
    graph_read_model: Annotated[
        Literal["disabled", "neo4j"],
        described_field("Graph read model for this app config."),
    ] = "disabled"
    neo4j_uri: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1),
        described_field("Neo4j URI for this app config.", repr=False),
    ] = None
    neo4j_username: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1),
        described_field("Neo4j username for this app config.", repr=False),
    ] = None
    neo4j_password: Annotated[
        SecretStr | None,
        described_field(
            "Neo4j password for this app config.", min_length=1, repr=False
        ),
    ] = None
    neo4j_database: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Neo4j database for this app config.", repr=False),
    ] = "neo4j"
    rag_vector_enabled: Annotated[
        bool, described_field("RAG vector enabled for this app config.")
    ] = True
    rag_embedding_provider: Annotated[
        EmbeddingProviderName,
        described_field("RAG embedding provider for this app config."),
    ] = "fastembed"
    rag_embedding_model: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("RAG embedding model for this app config."),
    ] = DEFAULT_EMBEDDING_MODEL
    rag_embedding_dimensions: Annotated[
        int, described_field("RAG embedding dimensions for this app config.", ge=1)
    ] = DEFAULT_EMBEDDING_DIMENSIONS
    rag_embedding_cache_dir: Annotated[
        str | None, described_field("RAG embedding cache dir for this app config.")
    ] = None
    rag_embedding_threads: Annotated[
        int, described_field("RAG embedding threads for this app config.", ge=1, le=32)
    ] = DEFAULT_EMBEDDING_THREADS
    rag_embedding_recovery_on_startup: Annotated[
        bool, described_field("RAG embedding recovery on startup for this app config.")
    ] = False
    rag_embedding_recovery_on_vault_reindex: Annotated[
        bool,
        described_field("RAG embedding recovery on vault reindex for this app config."),
    ] = False
    rag_embedding_recovery_batch_size: Annotated[
        int,
        described_field(
            "RAG embedding recovery batch size for this app config.", ge=1, le=1000
        ),
    ] = 250
    rag_embedding_recovery_max_batches: Annotated[
        int,
        described_field(
            "RAG embedding recovery max batches for this app config.", ge=1, le=1000
        ),
    ] = 40
    obsidian_vault_path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Obsidian vault path for this app config."),
    ] = "./data/obsidian-vault"
    alexandria_obsidian_root: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Alexandria Obsidian root for this app config."),
    ] = "Alexandria"
    obsidian_vault_config_path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Obsidian vault config path for this app config."),
    ] = "./data/obsidian-vault-config.json"
    memory_compact_note_dir: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Memory compact note dir for this app config."),
    ] = "Alexandria/Memory Compacts"
    operational_backup_root: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Operational backup root for this app config."),
    ] = "./data/operational-backups"
    operational_backup_retention_count: Annotated[
        int,
        described_field(
            "Operational backup retention count for this app config.", ge=1, le=365
        ),
    ] = 10
