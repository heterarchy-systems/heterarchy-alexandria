"""Credential and result contracts for librarian provider clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.repositories.librarian_repository import (
    IProviderSecretRepository as SecretResolver,
)
from app.connections.domain.types.librarian_provider_payload_types import (
    LibrarianProviderTestPayload,
)


class LibrarianProviderClientFactory(ABC):
    """Base contract for deterministic librarian provider connection testing."""

    @abstractmethod
    async def test_connection(
        self,
        provider: LibrarianProvider,
        secret_resolver: SecretResolver,
        test_query: str,
    ) -> ProviderClientTestResult:
        """Test one provider connection without exposing credentials.

        Args:
            provider [LibrarianProvider]: Value supplied to test_connection.
            secret_resolver [SecretResolver]: Value supplied to test_connection.
            test_query [str]: Value supplied to test_connection.

            provider: Provider used by this operation.
            secret_resolver: Secret resolver used by this operation.
            test_query: Test query used by this operation.
        Returns:
            ProviderClientTestResult: Value produced by test_connection.
        """


@dataclass(frozen=True, slots=True, repr=False)
class ApiKeyCredential:
    """Redacted API-key credential wrapper.

    Args:
        value: Raw API key value. The value is intentionally excluded from repr/str.
    """

    value: str

    def __repr__(self) -> str:
        """Return a redacted representation.

        Returns:
            str result produced by repr.
        """
        credential_repr = "ApiKeyCredential(value=***redacted***)"
        return credential_repr

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class ProviderClientTestResult:
    """Public provider test result that never carries credential material."""

    provider_id: str
    ok: bool
    message: str

    def as_public_dict(self) -> LibrarianProviderTestPayload:
        """Return the API-safe response payload.

        Args:
            None.

        Returns:
            LibrarianProviderTestPayload: Public result payload without credentials.
        """
        public_result: LibrarianProviderTestPayload = {
            "provider_id": self.provider_id,
            "ok": self.ok,
            "message": self.message,
        }
        return public_result
