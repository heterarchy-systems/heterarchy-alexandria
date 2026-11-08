"""Feature identities for environment-backed configuration sources."""

from enum import StrEnum


class SettingsModule(StrEnum):
    """Name the feature that owns a module settings file."""

    APP = "app"
    MCP = "mcp"
    MEMORY = "memory"
    VAULT = "vault"
    DATABASE = "database"
    REDIS = "redis"
