"""Authenticated encryption helpers for credential storage."""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
from dataclasses import dataclass
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_SIZE = 12
# Storage payload version is embedded inside the opaque base64 payload. Any
# version bump must add a migration that either upgrades or explicitly rejects
# old rows before runtime starts decrypting the new format.
_PAYLOAD_VERSION = 1
_PAYLOAD_VERSION_SIZE = 1
_AES_GCM_TAG_SIZE = 16
_MIN_ENCRYPTED_PAYLOAD_SIZE = _PAYLOAD_VERSION_SIZE + _NONCE_SIZE + _AES_GCM_TAG_SIZE
_LOCAL_DEV_KEY_SEED = "heterarchy-alexandria-local-development-secret-v1"


def _urlsafe_b64encode(value: bytes) -> str:
    """Encode bytes for compact storage.

    Args:
        value: Value being processed.

    Returns:
        str result produced by urlsafe b64encode.
    """
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    """Decode unpadded URL-safe base64 text.

    Args:
        value: Value being processed.

    Returns:
        bytes result produced by urlsafe b64decode.
    """
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(
            f"{value}{padding}".encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError("Value is not valid URL-safe base64") from exc


def _derive_key(raw_key: str) -> bytes:
    """Derive a 256-bit AES key from an environment-provided key string.

    Args:
        raw_key: Raw key used by this operation.

    Returns:
        bytes result produced by derive key.
    """
    try:
        decoded = _urlsafe_b64decode(raw_key)
    except ValueError:
        decoded = b""
    if len(decoded) == 32:
        return decoded
    return hashlib.sha256(raw_key.encode("utf-8")).digest()


@dataclass(frozen=True, slots=True)
class SecretCipherSettings:
    """Primitive settings needed to build the provider secret cipher."""

    app_name: str = "heterarchy-alexandria"
    app_env: Literal["local", "stage", "prod"] = "local"
    secret_encryption_key: str | None = None


@dataclass(frozen=True, slots=True)
class SecretCipher:
    """Encrypt and decrypt provider secrets before persistence.

    Args:
        key: Raw 256-bit AES-GCM key.
    """

    key: bytes

    @classmethod
    def from_settings(cls, settings: SecretCipherSettings) -> SecretCipher:
        """Build a cipher from primitive service settings.

        Local development gets a stable development key so tests and smoke runs work
        without extra setup. Stage/prod fail closed if SERVICE_SECRET_ENCRYPTION_KEY is
        missing.

        Args:
            settings: Primitive cipher settings.

        Returns:
            SecretCipher: Configured cipher.
        """
        configured_key = settings.secret_encryption_key
        if configured_key:
            return cls(key=_derive_key(configured_key))
        if settings.app_env == "local":
            local_seed = f"{settings.app_name}:{_LOCAL_DEV_KEY_SEED}"
            return cls(key=_derive_key(local_seed))
        raise RuntimeError(
            "SERVICE_SECRET_ENCRYPTION_KEY is required outside local env"
        )

    def encrypt(self, value: str) -> str:
        """Encrypt one secret string for database storage.

        Args:
            value: Value supplied to encrypt.

        Returns:
            str: Value produced by encrypt.
        """
        nonce = secrets.token_bytes(_NONCE_SIZE)
        ciphertext = AESGCM(self.key).encrypt(nonce, value.encode("utf-8"), None)
        payload = bytes([_PAYLOAD_VERSION]) + nonce + ciphertext
        return _urlsafe_b64encode(payload)

    def decrypt(self, stored_value: str) -> str:
        """Decrypt one stored secret string.

        Args:
            stored_value: Value supplied to decrypt.

        Returns:
            str: Value produced by decrypt.
        """
        try:
            payload = _urlsafe_b64decode(stored_value)
        except ValueError as exc:
            raise ValueError("Stored secret has an invalid encrypted format") from exc
        if len(payload) < _MIN_ENCRYPTED_PAYLOAD_SIZE:
            raise ValueError("Stored secret has an invalid encrypted format")
        version = payload[0]
        if version != _PAYLOAD_VERSION:
            raise ValueError("Stored secret has an invalid encrypted format")
        nonce_start = _PAYLOAD_VERSION_SIZE
        nonce_end = nonce_start + _NONCE_SIZE
        nonce = payload[nonce_start:nonce_end]
        ciphertext = payload[nonce_end:]
        try:
            plaintext = AESGCM(self.key).decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            raise ValueError("Stored secret cannot be decrypted") from exc
        return plaintext.decode("utf-8")
