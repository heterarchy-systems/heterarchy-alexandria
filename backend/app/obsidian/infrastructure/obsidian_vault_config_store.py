"""Persisted runtime Obsidian vault configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from typing_extensions import TypedDict

from app.obsidian.infrastructure.markdown.paths import (
    resolve_vault_path,
    safe_relative_path,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.serialization.orjson_codec import dumps_pretty_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue


class ObsidianVaultConfigPayload(TypedDict, closed=True):
    """JSON payload persisted for runtime Obsidian vault overrides."""

    vault_path: str
    alexandria_root: str


@dataclass(frozen=True, slots=True)
class ObsidianVaultConfig:
    """Resolved Obsidian vault path and managed Alexandria root."""

    vault_path: Path
    alexandria_root: str


class ObsidianVaultConfigStore:
    """Load and persist the active Obsidian vault configuration."""

    def __init__(
        self,
        default_vault_path: str,
        default_alexandria_root: str,
        config_path: str | None,
    ) -> None:
        """Initialize a runtime vault config store.

        Args:
            default_vault_path: AppConfig fallback vault path.
            default_alexandria_root: AppConfig fallback Alexandria root.
            config_path: Local JSON file used for runtime overrides.
        """
        self._default_config = self.normalized(
            vault_path=default_vault_path,
            alexandria_root=default_alexandria_root,
        )
        self._config_path = (
            None if config_path is None else _resolve_config_path(config_path)
        )
        self._runtime_override: ObsidianVaultConfig | None = None

    def current(self) -> ObsidianVaultConfig:
        """Return the persisted override or the AppConfig fallback.

        Returns:
            Active Obsidian vault configuration.
        """
        if self._runtime_override is not None:
            return self._runtime_override
        if self._config_path is None or not self._config_path.exists():
            return self._default_config
        try:
            payload = _payload_from_json(loads_json(self._config_path.read_bytes()))
        except (OSError, ValueError, TypeError) as exc:
            raise ObsidianValidationError(
                f"Obsidian vault settings are invalid: {self._config_path}"
            ) from exc
        return self.normalized(
            vault_path=payload["vault_path"],
            alexandria_root=payload["alexandria_root"],
        )

    def normalized(self, vault_path: str, alexandria_root: str) -> ObsidianVaultConfig:
        """Normalize raw vault settings without persisting them.

        Args:
            vault_path: User-supplied Obsidian vault root.
            alexandria_root: Managed folder inside the vault.

        Returns:
            Resolved vault configuration.
        """
        vault_path = vault_path.strip()
        if not vault_path:
            raise ObsidianValidationError("vault_path is required")
        root = _normalized_alexandria_root(alexandria_root)
        return ObsidianVaultConfig(
            vault_path=resolve_vault_path(vault_path),
            alexandria_root=root,
        )

    def save(self, config: ObsidianVaultConfig) -> None:
        """Persist a runtime vault override.

        Args:
            config: Normalized vault configuration to persist.

        Returns:
            None.
        """
        payload: JSONObject = {
            "vault_path": str(config.vault_path),
            "alexandria_root": config.alexandria_root,
        }
        self._runtime_override = config
        if self._config_path is None:
            return
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._config_path.with_suffix(f"{self._config_path.suffix}.tmp")
        temp_path.write_bytes(dumps_pretty_json(payload))
        temp_path.replace(self._config_path)

    def update(self, vault_path: str, alexandria_root: str) -> ObsidianVaultConfig:
        """Normalize and persist a runtime vault override.

        Args:
            vault_path: User-supplied Obsidian vault root.
            alexandria_root: Managed folder inside the vault.

        Returns:
            Persisted vault configuration.
        """
        config = self.normalized(vault_path=vault_path, alexandria_root=alexandria_root)
        self.save(config)
        return config


def _resolve_config_path(config_path: str) -> Path:
    """Resolve config path.

    Args:
        config_path: Config path used by this operation.

    Returns:
        Resolved config path.
    """
    path = Path(config_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _normalized_alexandria_root(alexandria_root: str) -> str:
    """Execute normalized alexandria root.

    Args:
        alexandria_root: Alexandria root used by this operation.

    Returns:
        str result produced by normalized alexandria root.
    """
    root = alexandria_root.strip() or "."
    return str(safe_relative_path(root))


def _payload_from_json(value: JSONValue) -> ObsidianVaultConfigPayload:
    """Execute payload from json.

    Args:
        value: Value being processed.

    Returns:
        ObsidianVaultConfigPayload result produced by payload from json.
    """
    if not isinstance(value, dict):
        raise ObsidianValidationError("Obsidian vault settings must be a JSON object")
    vault_path = value.get("vault_path")
    alexandria_root = value.get("alexandria_root")
    if not isinstance(vault_path, str) or not isinstance(alexandria_root, str):
        raise ObsidianValidationError(
            "Obsidian vault settings require vault_path and alexandria_root"
        )
    return ObsidianVaultConfigPayload(
        vault_path=vault_path,
        alexandria_root=alexandria_root,
    )
