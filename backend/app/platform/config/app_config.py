"""Common service configuration model.

This module reads shared service configuration from ``.env`` and environment
variables. Most service fields use the ``SERVICE_`` prefix.
"""

from __future__ import annotations

from typing import Final, Literal
from urllib.parse import ParseResult, urlparse

from app.mcp_server.type_validate.auth_contracts import McpAuthMode
from app.memory.application.retrieval.embedding_contract import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_THREADS,
)
from app.memory.application.retrieval.embedding_factory import EmbeddingProviderName
from app.shared.utils.config import settings_model_config
from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings

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


class AppConfig(BaseSettings):
    """Common service settings model.

    Role:
        Centralizes global service settings such as app name, environment, version,
        and log level. The public method count exceeds the normal review threshold
        because Pydantic validators and normalized configuration projections must
        remain attached to the single external settings boundary.
    """

    model_config = {
        **settings_model_config(env_prefix="SERVICE_"),
        "populate_by_name": True,
    }

    app_name: str = Field(default="heterarchy-alexandria")
    app_env: Literal["local", "stage", "prod"] = Field(default="local")
    app_version: str = Field(default="0.1.0")
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    secret_encryption_key: str | None = Field(default=None)

    mcp_transport_host: str = Field(default="0.0.0.0", min_length=1)
    mcp_auth_mode: McpAuthMode = Field(default=McpAuthMode.NONE)
    mcp_oauth_issuer: str | None = Field(default=None)
    mcp_oauth_audience: str | None = Field(default=None)
    mcp_oauth_jwks_url: str | None = Field(default=None)
    mcp_oauth_resource: str | None = Field(default=None)
    mcp_oauth_authorization_servers: str | None = Field(default=None)
    mcp_oauth_required_scope: str = Field(default="alexandria:mcp")
    mcp_local_approval_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SERVICE_MCP_LOCAL_APPROVAL_KEY",
            "ALEXANDRIA_OPERATOR_API_KEY",
        ),
        repr=False,
    )
    mcp_local_access_token_ttl_seconds: int = Field(
        default=DEFAULT_MCP_LOCAL_ACCESS_TOKEN_TTL_SECONDS,
        ge=5 * 60,
        le=24 * 60 * 60,
    )
    mcp_local_refresh_token_ttl_seconds: int = Field(
        default=DEFAULT_MCP_LOCAL_REFRESH_TOKEN_TTL_SECONDS,
        ge=24 * 60 * 60,
        le=365 * 24 * 60 * 60,
    )
    mcp_local_authorization_code_ttl_seconds: int = Field(
        default=DEFAULT_MCP_LOCAL_AUTHORIZATION_CODE_TTL_SECONDS,
        ge=60,
        le=10 * 60,
    )
    mcp_local_approval_ttl_seconds: int = Field(
        default=DEFAULT_MCP_LOCAL_APPROVAL_TTL_SECONDS,
        ge=60,
        le=30 * 60,
    )
    mcp_local_pairing_code_ttl_seconds: int = Field(
        default=DEFAULT_MCP_LOCAL_PAIRING_CODE_TTL_SECONDS,
        ge=60,
        le=10 * 60,
    )
    mcp_local_max_approval_attempts: int = Field(
        default=DEFAULT_MCP_LOCAL_MAX_APPROVAL_ATTEMPTS,
        ge=1,
        le=10,
    )

    codex_oauth_issuer: str = Field(default=DEFAULT_CODEX_OAUTH_ISSUER, min_length=1)
    codex_oauth_client_id: str = Field(
        default=DEFAULT_CODEX_OAUTH_CLIENT_ID,
        min_length=1,
    )
    codex_oauth_device_expires_in_seconds: int = Field(
        default=DEFAULT_CODEX_OAUTH_DEVICE_EXPIRES_IN_SECONDS,
        ge=60,
        le=60 * 60,
    )
    codex_oauth_min_poll_interval_seconds: int = Field(
        default=DEFAULT_CODEX_OAUTH_MIN_POLL_INTERVAL_SECONDS,
        ge=1,
        le=60,
    )

    memory_reconciliation_provider_id: str | None = Field(default=None)
    memory_reconciliation_model: str = Field(
        default=DEFAULT_MEMORY_RECONCILIATION_MODEL,
        min_length=1,
    )
    memory_reconciliation_provider_timeout_seconds: float = Field(
        default=DEFAULT_MEMORY_RECONCILIATION_PROVIDER_TIMEOUT_SECONDS,
        gt=0,
        le=300,
    )

    graph_read_model: Literal["disabled", "neo4j"] = Field(default="disabled")
    neo4j_uri: str | None = Field(default=None, min_length=1, repr=False)
    neo4j_username: str | None = Field(default=None, min_length=1, repr=False)
    neo4j_password: SecretStr | None = Field(
        default=None,
        min_length=1,
        repr=False,
    )
    neo4j_database: str = Field(default="neo4j", min_length=1, repr=False)

    rag_vector_enabled: bool = Field(default=True)
    rag_embedding_provider: EmbeddingProviderName = Field(default="fastembed")
    rag_embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL, min_length=1)
    rag_embedding_dimensions: int = Field(default=DEFAULT_EMBEDDING_DIMENSIONS, ge=1)
    rag_embedding_cache_dir: str | None = Field(default=None)
    rag_embedding_threads: int = Field(default=DEFAULT_EMBEDDING_THREADS, ge=1, le=32)
    rag_embedding_recovery_on_startup: bool = Field(default=False)
    rag_embedding_recovery_on_vault_reindex: bool = Field(default=False)
    rag_embedding_recovery_batch_size: int = Field(default=250, ge=1, le=1000)
    rag_embedding_recovery_max_batches: int = Field(default=40, ge=1, le=1000)

    obsidian_vault_path: str = Field(default="./data/obsidian-vault", min_length=1)
    alexandria_obsidian_root: str = Field(default="Alexandria", min_length=1)
    obsidian_vault_config_path: str = Field(
        default="./data/obsidian-vault-config.json",
        min_length=1,
    )
    memory_compact_note_dir: str = Field(
        default="Alexandria/Memory Compacts",
        min_length=1,
    )
    operational_backup_root: str = Field(
        default="./data/operational-backups",
        min_length=1,
    )
    operational_backup_retention_count: int = Field(default=10, ge=1, le=365)

    @field_validator(
        "mcp_oauth_issuer",
        "mcp_oauth_audience",
        "mcp_oauth_jwks_url",
        "mcp_oauth_resource",
        "mcp_oauth_authorization_servers",
        mode="before",
    )
    @classmethod
    def normalize_optional_oauth_text(cls, value: str | None) -> str | None:
        """Normalize optional OAuth text without enabling a mode implicitly.

        Args:
            value: Value supplied to normalize_optional_oauth_text.
        Returns:
            str | None: Value produced by normalize_optional_oauth_text."""
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("memory_reconciliation_provider_id")
    @classmethod
    def normalize_memory_reconciliation_provider_id(
        cls,
        value: str | None,
    ) -> str | None:
        """Normalize the optional provider id without enabling one implicitly.

        Args:
            value: Value supplied to normalize_memory_reconciliation_provider_id.
        Returns:
            str | None: Value produced by normalize_memory_reconciliation_provider_id."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("neo4j_uri", "neo4j_username", mode="before")
    @classmethod
    def normalize_optional_neo4j_text(cls, value: str | None) -> str | None:
        """Normalize optional Neo4j connection text before fail-closed checks.

        Args:
            value: Optional Neo4j connection field value.

        Returns:
            Trimmed value, or None when blank.
        """
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("neo4j_password", mode="before")
    @classmethod
    def normalize_optional_neo4j_password(
        cls,
        value: str | SecretStr | None,
    ) -> str | SecretStr | None:
        """Normalize optional Neo4j password without leaking the value.

        Args:
            value: Raw secret string or already parsed secret.

        Returns:
            Trimmed secret value, or None when blank.
        """
        if isinstance(value, SecretStr):
            normalized = value.get_secret_value().strip()
            return SecretStr(normalized) if normalized else None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("neo4j_database")
    @classmethod
    def normalize_neo4j_database(cls, value: str) -> str:
        """Normalize and reject blank Neo4j database names.

        Args:
            value: Configured Neo4j database name.

        Returns:
            Trimmed database name.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("neo4j_database must not be blank")
        return normalized

    @field_validator("memory_reconciliation_model")
    @classmethod
    def normalize_memory_reconciliation_model(cls, value: str) -> str:
        """Normalize the configured fallback model name.

        Args:
            value: Value supplied to normalize_memory_reconciliation_model.
        Returns:
            str: Value produced by normalize_memory_reconciliation_model."""
        return value.strip()

    @model_validator(mode="after")
    def validate_mcp_oauth_configuration(self) -> AppConfig:
        """Fail closed when the selected MCP OAuth mode is incomplete.

        Returns:
            AppConfig: Value produced by validate_mcp_oauth_configuration."""
        if self.mcp_auth_mode is McpAuthMode.NONE:
            return self
        if self.mcp_auth_mode is McpAuthMode.OAUTH2:
            _require_values(
                "MCP OAuth mode",
                (
                    ("mcp_oauth_issuer", self.mcp_oauth_issuer),
                    ("mcp_oauth_audience", self.mcp_oauth_audience),
                    ("mcp_oauth_jwks_url", self.mcp_oauth_jwks_url),
                ),
            )
            return self
        _require_values(
            "MCP local OAuth mode",
            (
                ("mcp_oauth_issuer", self.mcp_oauth_issuer),
                ("mcp_oauth_resource", self.mcp_oauth_resource),
                ("mcp_local_approval_key", self.mcp_local_approval_key),
            ),
        )
        issuer = self.mcp_oauth_issuer or ""
        resource = self.mcp_oauth_resource or ""
        _validate_local_oauth_urls(issuer=issuer, resource=resource)
        approval_key = self.mcp_local_approval_key_value()
        if len(approval_key) < 24:
            raise ValueError(
                "MCP local OAuth approval key must contain at least 24 characters"
            )
        return self

    @model_validator(mode="after")
    def validate_graph_read_model_configuration(self) -> AppConfig:
        """Require only the connection values consumed by the enabled adapter.

        Returns:
            AppConfig: Validated service configuration.
        """
        if self.graph_read_model == "disabled":
            return self
        _require_values(
            "Neo4j graph read model",
            (
                ("neo4j_uri", self.neo4j_uri),
                ("neo4j_username", self.neo4j_username),
                ("neo4j_password", self.neo4j_password),
            ),
        )
        return self

    def neo4j_password_value(self) -> str:
        """Return the Neo4j password only at the driver-construction boundary.

        Returns:
            str: Configured Neo4j credential, or an empty value when disabled.
        """
        if self.neo4j_password is None:
            return ""
        return self.neo4j_password.get_secret_value()

    def mcp_oauth_required_scopes(self) -> tuple[str, ...]:
        """Return normalized MCP OAuth scopes from configuration.

        Returns:
            tuple[str, ...]: Value produced by mcp_oauth_required_scopes."""
        return tuple(scope for scope in self.mcp_oauth_required_scope.split() if scope)

    def mcp_local_oauth_default_scopes(self) -> tuple[str, ...]:
        """Return required scopes plus refresh-token connectivity scope.

        Returns:
            tuple[str, ...]: Value produced by mcp_local_oauth_default_scopes."""
        return tuple(
            dict.fromkeys((*self.mcp_oauth_required_scopes(), "offline_access"))
        )

    def mcp_local_approval_key_value(self) -> str:
        """Return the configured local approval credential after mode validation.

        Returns:
            str: Value produced by mcp_local_approval_key_value."""
        if self.mcp_local_approval_key is None:
            raise RuntimeError("MCP local OAuth approval key is not configured")
        return self.mcp_local_approval_key.get_secret_value()

    def mcp_oauth_authorization_server_urls(self) -> tuple[str, ...]:
        """Return advertised OAuth authorization-server metadata URLs.

        Returns:
            tuple[str, ...]: Value produced by mcp_oauth_authorization_server_urls."""
        if self.mcp_oauth_authorization_servers:
            return tuple(
                item.strip()
                for item in self.mcp_oauth_authorization_servers.split(",")
                if item.strip()
            )
        if self.mcp_oauth_issuer:
            return (self.mcp_oauth_issuer,)
        return ()


def _require_values(
    mode_name: str,
    values: tuple[tuple[str, str | SecretStr | None], ...],
) -> None:
    missing = [name for name, value in values if value is None or value == ""]
    if missing:
        raise ValueError(f"{mode_name} requires: {', '.join(missing)}")


def _validate_local_oauth_urls(*, issuer: str, resource: str) -> None:
    issuer_url = urlparse(issuer)
    resource_url = urlparse(resource)
    _validate_oauth_url("mcp_oauth_issuer", issuer_url)
    _validate_oauth_url("mcp_oauth_resource", resource_url)
    if issuer_url.path not in {"", "/"}:
        raise ValueError("mcp_oauth_issuer must not include a path")
    if resource_url.path.rstrip("/") != "/mcp":
        raise ValueError("mcp_oauth_resource must end with /mcp")
    issuer_origin = (issuer_url.scheme, issuer_url.hostname, issuer_url.port)
    resource_origin = (resource_url.scheme, resource_url.hostname, resource_url.port)
    if issuer_origin != resource_origin:
        raise ValueError("MCP local OAuth issuer and resource must share one origin")


def _validate_oauth_url(name: str, parsed: ParseResult) -> None:
    scheme = parsed.scheme
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError(f"{name} must include a hostname")
    if scheme != "https" and not (scheme == "http" and hostname in _LOCAL_HTTP_HOSTS):
        raise ValueError(f"{name} must use HTTPS outside localhost")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{name} must not include userinfo")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not include query or fragment")
