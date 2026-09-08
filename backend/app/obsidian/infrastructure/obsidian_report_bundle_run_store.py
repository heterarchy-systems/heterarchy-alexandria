"""Durable local idempotency checkpoints for report bundle orchestration."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Annotated, TypeVar

from pydantic import TypeAdapter, ValidationError

from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.serialization.model_codec import schema_payload
from app.shared.serialization.orjson_codec import dumps_pretty_json, loads_json
from app.shared.types.extra_types import JSONObject

RecordT = TypeVar("RecordT")


class _TypedCheckpointEnvelope(StrictSchemaModel):
    """Keep operation identity outside the operation-specific persisted record."""

    kind: Annotated[
        str, described_field("Checkpoint operation namespace.", min_length=1)
    ]
    record: Annotated[
        JSONObject, described_field("Typed operation checkpoint payload.")
    ]


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
        content = self._read_checkpoint(idempotency_key)
        if content is None:
            return None
        try:
            value = loads_json(content)
        except (ValueError, TypeError) as error:
            raise ObsidianCheckpointRecoveryRequiredError(
                self._path(idempotency_key).stem
            ) from error
        if not isinstance(value, dict):
            raise ObsidianCheckpointRecoveryRequiredError(
                self._path(idempotency_key).stem
            )
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
            self._fsync_root()
        finally:
            temporary.unlink(missing_ok=True)

    def load_typed(
        self,
        idempotency_key: str,
        adapter: TypeAdapter[RecordT],
    ) -> RecordT | None:
        """Load and validate one checkpoint through its explicit type adapter.

        Only a missing file means no checkpoint. Existing invalid records require
        durable recovery and can never be treated as fresh mutation admission.

        Args:
            idempotency_key: Opaque operation key used for the checkpoint path.
            adapter: Pydantic adapter for the operation-owned checkpoint type.

        Returns:
            Validated record, or None when the checkpoint file does not exist.
        """
        content = self._read_checkpoint(idempotency_key)
        if content is None:
            return None
        try:
            envelope = _TypedCheckpointEnvelope.model_validate_json(content)
            if envelope.kind != idempotency_key.partition(":")[0]:
                raise ValueError("checkpoint operation namespace mismatch")
            return adapter.validate_json(
                dumps_pretty_json(envelope.record), strict=True
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise ObsidianCheckpointRecoveryRequiredError(
                self._path(idempotency_key).stem
            ) from error

    def _read_checkpoint(self, idempotency_key: str) -> bytes | None:
        """Distinguish source absence from corruption or unreadable operation state."""
        path = self._path(idempotency_key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ObsidianCheckpointRecoveryRequiredError(path.stem) from error

    def save_typed(
        self,
        idempotency_key: str,
        record: RecordT,
        adapter: TypeAdapter[RecordT],
    ) -> None:
        """Serialize one typed checkpoint through its explicit adapter.

        Args:
            idempotency_key: Opaque operation key used for the checkpoint path.
            record: Typed operation checkpoint.
            adapter: Pydantic adapter for the operation-owned checkpoint type.
        """
        encoded = adapter.dump_python(record, mode="json")
        if not isinstance(encoded, dict):
            raise TypeError("typed report-bundle checkpoint must encode as an object")
        self.save(
            idempotency_key,
            schema_payload(
                _TypedCheckpointEnvelope(
                    kind=idempotency_key.partition(":")[0], record=encoded
                )
            ),
        )

    def _path(self, idempotency_key: str) -> Path:
        """Execute path.

        Args:
            idempotency_key: Idempotency key used by this operation.

        Returns:
            Path result produced by path.
        """
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self._root / f"{digest}.json"

    def _fsync_root(self) -> None:
        """Flush the checkpoint directory entry after an atomic replacement."""
        descriptor = os.open(self._root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
