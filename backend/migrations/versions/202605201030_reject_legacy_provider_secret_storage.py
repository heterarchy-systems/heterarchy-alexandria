"""Reject legacy provider secret storage values.

Revision ID: 202605201030_reject_legacy_provider_secret_storage
Revises: 202605201020_normalize_legacy_sqlite_datetimes
Create Date: 2026-05-20 10:30:00.000000
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202605201030_reject_legacy_provider_secret_storage"
down_revision: str | None = "202605201020_normalize_legacy_sqlite_datetimes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Freeze the accepted secret-storage format for this historical migration. Any
# future SecretCipher version bump needs its own migration instead of editing
# this revision in place.
_SECRET_PAYLOAD_VERSION = 1
_MIN_SECRET_PAYLOAD_SIZE = 1 + 12 + 16
_OAUTH_MANAGED_SECRET_KEYS = frozenset(
    {
        "oauth_access_token",
        "oauth_refresh_token",
        "oauth_expires_at",
        "oauth_token_type",
        "oauth_scope",
        "oauth_device_code",
        "oauth_device_expires_at",
        "oauth_poll_interval_seconds",
    }
)


def _decoded_storage_payload(value: str) -> bytes | None:
    """Decode one opaque URL-safe base64 secret payload.

    Args:
        value: Stored provider secret value.

    Returns:
        Decoded payload bytes, or ``None`` when the value is not current storage.
    """
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(
            f"{value}{padding}".encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except binascii.Error, UnicodeEncodeError:
        return None


def _is_current_secret_storage(value: str) -> bool:
    """Return whether a stored secret has the current opaque versioned format.

    Args:
        value: Stored provider secret value.

    Returns:
        True when the payload shape is current.
    """
    payload = _decoded_storage_payload(value)
    if payload is None:
        return False
    return (
        len(payload) >= _MIN_SECRET_PAYLOAD_SIZE
        and payload[0] == _SECRET_PAYLOAD_VERSION
    )


def upgrade() -> None:
    """Reject unsafe legacy secrets and clear invalid OAuth credentials."""
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, provider_id, key_name, value
            FROM librarian_provider_secrets
            """
        )
    ).fetchall()
    legacy_keys: list[str] = []
    oauth_secret_ids: list[str] = []
    for row in rows:
        secret_id = str(row[0])
        provider_id = str(row[1])
        key_name = str(row[2])
        value = str(row[3])
        if _is_current_secret_storage(value):
            continue
        if key_name in _OAUTH_MANAGED_SECRET_KEYS:
            oauth_secret_ids.append(secret_id)
            continue
        legacy_keys.append(f"{provider_id}:{key_name}")

    for secret_id in oauth_secret_ids:
        connection.execute(
            sa.text(
                """
                DELETE FROM librarian_provider_secrets
                WHERE id = :secret_id
                """
            ),
            {"secret_id": secret_id},
        )

    if legacy_keys:
        joined = ", ".join(legacy_keys[:10])
        raise RuntimeError(
            "Legacy plaintext or old-version provider secrets must be rotated "
            f"before upgrade. Offending provider/key pairs: {joined}"
        )


def downgrade() -> None:
    """No schema downgrade is required for the validation-only migration."""
