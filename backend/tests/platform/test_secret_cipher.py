"""Secret cipher behavior tests."""

from __future__ import annotations

import base64
import binascii
from typing import Literal

import pytest
from app.shared.security.secret_cipher import SecretCipher, SecretCipherSettings


def _cipher_settings(
    *,
    app_env: Literal["local", "stage", "prod"] = "local",
    secret_encryption_key: str | None = None,
) -> SecretCipherSettings:
    return SecretCipherSettings(
        app_name="heterarchy-alexandria",
        app_env=app_env,
        secret_encryption_key=secret_encryption_key,
    )


def _storage_payload(stored_value: str) -> bytes:
    """Return raw bytes from an opaque secret storage value.

    Args:
        stored_value: URL-safe base64 storage value.

    Returns:
        Decoded storage payload bytes.
    """
    padding = "=" * (-len(stored_value) % 4)
    try:
        return base64.b64decode(
            f"{stored_value}{padding}".encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise AssertionError("encrypted value should be URL-safe base64") from exc


def _storage_value(payload: bytes) -> str:
    """Return a storage value from raw opaque payload bytes.

    Args:
        payload: Raw opaque secret payload.

    Returns:
        URL-safe base64 storage value.
    """
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def test_secret_cipher_encrypts_without_plaintext_and_round_trips() -> None:
    """SecretCipher should hide plaintext while preserving resolvability."""
    cipher = SecretCipher.from_settings(
        _cipher_settings(
            app_env="local",
            secret_encryption_key="test-encryption-key",
        )
    )

    encrypted = cipher.encrypt("do-not-store-plain")

    assert not encrypted.startswith("enc:v1:")
    assert ":" not in encrypted
    assert "do-not-store-plain" not in encrypted
    assert _storage_payload(encrypted)[0] == 1
    assert cipher.decrypt(encrypted) == "do-not-store-plain"


def test_secret_cipher_rejects_plaintext_storage_values() -> None:
    """SecretCipher should fail closed instead of accepting legacy plaintext."""
    cipher = SecretCipher.from_settings(
        _cipher_settings(
            app_env="local",
            secret_encryption_key="test-encryption-key",
        )
    )

    with pytest.raises(ValueError, match="invalid encrypted format"):
        cipher.decrypt("plain-secret")


def test_secret_cipher_rejects_tampered_storage_values() -> None:
    """SecretCipher should fail closed when ciphertext authentication fails."""
    cipher = SecretCipher.from_settings(
        _cipher_settings(
            app_env="local",
            secret_encryption_key="test-encryption-key",
        )
    )
    encrypted = cipher.encrypt("do-not-store-plain")
    tampered_payload = bytearray(_storage_payload(encrypted))
    tampered_payload[-1] ^= 1
    tampered = _storage_value(bytes(tampered_payload))

    with pytest.raises(ValueError, match="cannot be decrypted"):
        cipher.decrypt(tampered)


def test_secret_cipher_requires_configured_key_outside_local_env() -> None:
    """Stage/prod should fail closed without an explicit encryption key."""
    with pytest.raises(RuntimeError, match="SERVICE_SECRET_ENCRYPTION_KEY"):
        SecretCipher.from_settings(_cipher_settings(app_env="prod"))
