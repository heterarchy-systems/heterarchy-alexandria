"""Durable local idempotency checkpoints for report bundle orchestration."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from app.shared.serialization.orjson_codec import dumps_pretty_json, loads_json
from app.shared.types.extra_types import JSONObject


class ObsidianReportBundleRunStore:
    """Persist non-canonical operation state outside the managed Markdown root."""

    def __init__(self, vault_path: Path) -> None:
        """Initialize ObsidianReportBundleRunStore state and dependencies.

        Args:
            vault_path: Vault path used by this operation.
        """
        self._root = vault_path / ".alexandria" / "report-bundle-runs"

    def load(self, idempotency_key: str) -> JSONObject | None:
        """Load one checkpoint by an opaque idempotency key hash.

        Args:
            idempotency_key: Value supplied to load.

        Returns:
            Result produced by load.
        """
        path = self._path(idempotency_key)
        if not path.exists():
            return None
        value = loads_json(path.read_bytes())
        if not isinstance(value, dict):
            return None
        return value

    def save(self, idempotency_key: str, record: JSONObject) -> None:
        """Atomically replace one credential-free operation checkpoint.

        Args:
            idempotency_key: Value supplied to save.
            record: Value supplied to save.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        destination = self._path(idempotency_key)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._root,
            prefix=f".{destination.stem}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(dumps_pretty_json(record))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _path(self, idempotency_key: str) -> Path:
        """Execute path.

        Args:
            idempotency_key: Idempotency key used by this operation.

        Returns:
            Path result produced by path.
        """
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self._root / f"{digest}.json"
