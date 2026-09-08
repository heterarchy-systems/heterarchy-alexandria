"""Contract tests for portable operational backup manifests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.operations.application.backup.operational_backup_manifest import (
    OperationalBackupArtifact,
    OperationalBackupManifest,
)
from app.shared.serialization.orjson_codec import dumps_json
from pydantic import ValidationError


def _manifest_payload() -> dict[str, object]:
    """Return one JSON-compatible backup manifest fixture."""
    return {
        "backup_id": "backup-20260821",
        "created_at": "2026-08-21T01:30:00Z",
        "vault_source_path": "/vault/Alexandria",
        "alexandria_root": "Alexandria",
        "operational_database_source_path": "/data/postgres.dump",
        "artifacts": [
            {
                "kind": "canonical_vault",
                "relative_path": "vault.tar.enc",
                "sha256": "a" * 64,
                "size_bytes": 120,
                "plaintext_sha256": "b" * 64,
            },
            {
                "kind": "operational_database",
                "relative_path": "postgres.dump.enc",
                "sha256": "c" * 64,
                "size_bytes": 80,
                "plaintext_sha256": "d" * 64,
            },
        ],
    }


def test_backup_package_exposes_strict_versioned_manifest_contract() -> None:
    """The focused backup package should preserve the public manifest contract."""
    manifest = OperationalBackupManifest.model_validate_json(
        dumps_json(_manifest_payload())
    )

    assert manifest.schema_version == 2
    assert manifest.encryption == "fernet"
    assert manifest.total_bytes == 200
    assert manifest.created_datetime == datetime(2026, 8, 21, 1, 30, tzinfo=UTC)
    assert isinstance(manifest.artifacts[0], OperationalBackupArtifact)


def test_backup_manifest_rejects_unsupported_schema_version() -> None:
    """Portable backups must fail closed on an unsupported manifest version."""
    payload = _manifest_payload()
    payload["schema_version"] = 1

    with pytest.raises(ValidationError, match="schema_version"):
        OperationalBackupManifest.model_validate_json(dumps_json(payload))
