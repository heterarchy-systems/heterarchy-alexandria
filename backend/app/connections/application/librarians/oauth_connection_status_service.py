"""Storage-backed OAuth connection status query service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.connections.application.librarians.oauth_secret_store import (
    DEVICE_FLOW_SECRET_KEYS,
    LibrarianOAuthSecretStore,
)
from app.connections.application.librarians.oauth_status_evaluator import (
    LibrarianOAuthStatusEvaluator,
    OAuthCredentialSnapshot,
)
from app.connections.domain.event_enum.provider_enums import (
    OAuthConnectionStatus,
    ProviderSecretKey,
)
from app.connections.domain.types.librarian_oauth_payload_types import (
    LibrarianOAuthStatusPayload,
)
from app.shared.types.types_convert_utils import aware_utc_datetime


class LibrarianOAuthConnectionStatusService:
    """Read encrypted credentials and derive one public connection status."""

    def __init__(
        self,
        secret_store: LibrarianOAuthSecretStore,
        evaluator: LibrarianOAuthStatusEvaluator,
        now_provider: Callable[[], datetime],
    ) -> None:
        """Create the status query service.

        Args:
            secret_store: Encrypted OAuth credential boundary.
            evaluator: Pure OAuth status policy.
            now_provider: Clock boundary for deterministic expiry evaluation.
        """
        self._secret_store = secret_store
        self._evaluator = evaluator
        self._now_provider = now_provider

    async def current_status(
        self,
        provider_id: str,
    ) -> LibrarianOAuthStatusPayload:
        """Return current public OAuth status for one provider.

        Args:
            provider_id: Provider identifier.

        Returns:
            Public OAuth status without credential material.
        """
        device_code = await self._secret_store.resolve(
            provider_id,
            ProviderSecretKey.OAUTH_DEVICE_CODE,
        )
        credentials = OAuthCredentialSnapshot(
            device_code=device_code,
            device_expires_at=await self._secret_store.expires_at(
                provider_id,
                ProviderSecretKey.OAUTH_DEVICE_EXPIRES_AT,
            ),
            access_token=await self._secret_store.resolve(
                provider_id,
                ProviderSecretKey.OAUTH_ACCESS_TOKEN,
            ),
            expires_at=await self._secret_store.expires_at(
                provider_id,
                ProviderSecretKey.OAUTH_EXPIRES_AT,
            ),
            refresh_token=await self._secret_store.resolve(
                provider_id,
                ProviderSecretKey.OAUTH_REFRESH_TOKEN,
            ),
        )
        payload = self._evaluator.evaluate(
            provider_id=provider_id,
            credentials=credentials,
            now=aware_utc_datetime(self._now_provider()),
        )
        if (
            payload["status"] is OAuthConnectionStatus.EXPIRED
            and device_code is not None
        ):
            await self._secret_store.delete(provider_id, DEVICE_FLOW_SECRET_KEYS)
        return payload
