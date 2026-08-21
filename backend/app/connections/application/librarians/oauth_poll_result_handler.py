"""OAuth device-flow poll result application service."""

from __future__ import annotations

from app.connections.application.librarians.oauth_secret_store import (
    DEVICE_FLOW_SECRET_KEYS,
    LibrarianOAuthSecretStore,
)
from app.connections.application.librarians.oauth_status_evaluator import (
    LibrarianOAuthStatusEvaluator,
)
from app.connections.domain.contracts.librarian_oauth_contracts import OAuthPollResult
from app.connections.domain.event_enum.provider_enums import (
    OAuthConnectionStatus,
    OAuthPollStatus,
)
from app.connections.domain.types.librarian_oauth_payload_types import (
    LibrarianOAuthStatusPayload,
)


class LibrarianOAuthPollResultHandler:
    """Persist successful tokens and map provider poll results to public status."""

    def __init__(
        self,
        secret_store: LibrarianOAuthSecretStore,
        evaluator: LibrarianOAuthStatusEvaluator,
    ) -> None:
        """Create the poll result handler.

        Args:
            secret_store: Encrypted OAuth credential boundary.
            evaluator: Public status payload builder.
        """
        self._secret_store = secret_store
        self._evaluator = evaluator

    async def handle(
        self,
        provider_id: str,
        poll_result: OAuthPollResult,
    ) -> LibrarianOAuthStatusPayload:
        """Apply one provider poll result.

        Args:
            provider_id: Provider identifier.
            poll_result: OAuth provider poll result.

        Returns:
            Public connection status without token material.
        """
        if poll_result.status is OAuthPollStatus.CONNECTED:
            token_set = poll_result.token_set
            if token_set is None:
                raise ValueError("connected OAuth poll result requires tokens")
            await self._secret_store.store_token_set(provider_id, token_set)
            await self._secret_store.delete(provider_id, DEVICE_FLOW_SECRET_KEYS)
            return self._evaluator.payload(
                provider_id=provider_id,
                status=OAuthConnectionStatus.CONNECTED,
                connected=True,
                expires_at=token_set.expires_at,
                refresh_required=False,
                message=None,
            )
        if poll_result.status is OAuthPollStatus.EXPIRED:
            await self._secret_store.delete(provider_id, DEVICE_FLOW_SECRET_KEYS)
            return self._evaluator.payload(
                provider_id=provider_id,
                status=OAuthConnectionStatus.EXPIRED,
                connected=False,
                expires_at=None,
                refresh_required=False,
                message=poll_result.message,
            )
        if poll_result.status is OAuthPollStatus.FAILED:
            return self._evaluator.payload(
                provider_id=provider_id,
                status=OAuthConnectionStatus.FAILED,
                connected=False,
                expires_at=None,
                refresh_required=False,
                message=poll_result.message,
            )
        return self._evaluator.payload(
            provider_id=provider_id,
            status=OAuthConnectionStatus.PENDING,
            connected=False,
            expires_at=None,
            refresh_required=False,
            message=poll_result.message,
        )
