"""Pure OAuth connection status evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from app.connections.domain.event_enum.provider_enums import OAuthConnectionStatus
from app.connections.domain.types.librarian_oauth_payload_types import (
    LibrarianOAuthStatusPayload,
)
from app.shared.types.types_convert_utils import aware_utc_datetime

OAUTH_REFRESH_SKEW: Final[timedelta] = timedelta(seconds=120)


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuthCredentialSnapshot:
    """Validated credential presence and expiry values for status evaluation."""

    device_code: str | None
    device_expires_at: datetime | None
    access_token: str | None
    expires_at: datetime | None
    refresh_token: str | None


class LibrarianOAuthStatusEvaluator:
    """Derive public OAuth status without reading or mutating secret storage."""

    def evaluate(
        self,
        provider_id: str,
        credentials: OAuthCredentialSnapshot,
        now: datetime,
    ) -> LibrarianOAuthStatusPayload:
        """Evaluate one provider's current connection state.

        Args:
            provider_id: Provider identifier.
            credentials: Resolved credential snapshot.
            now: Current aware timestamp.

        Returns:
            Public OAuth status payload without token material.
        """
        current = aware_utc_datetime(now)
        if credentials.device_code is not None:
            if (
                credentials.device_expires_at is None
                or credentials.device_expires_at > current
            ):
                return self.payload(
                    provider_id=provider_id,
                    status=OAuthConnectionStatus.PENDING,
                    connected=False,
                    expires_at=None,
                    refresh_required=False,
                    message=None,
                )
            return self.payload(
                provider_id=provider_id,
                status=OAuthConnectionStatus.EXPIRED,
                connected=False,
                expires_at=None,
                refresh_required=False,
                message="OAuth device flow expired",
            )
        if credentials.access_token is None:
            return self.payload(
                provider_id=provider_id,
                status=OAuthConnectionStatus.NOT_CONNECTED,
                connected=False,
                expires_at=credentials.expires_at,
                refresh_required=False,
                message=None,
            )
        if credentials.expires_at is None:
            return self._missing_expiry_payload(
                provider_id=provider_id,
                refresh_token=credentials.refresh_token,
            )
        if credentials.expires_at <= current:
            if credentials.refresh_token is None:
                return self.payload(
                    provider_id=provider_id,
                    status=OAuthConnectionStatus.EXPIRED,
                    connected=False,
                    expires_at=credentials.expires_at,
                    refresh_required=False,
                    message="OAuth access token expired",
                )
            return self._refresh_required_payload(
                provider_id=provider_id,
                expires_at=credentials.expires_at,
            )
        if credentials.expires_at <= current + OAUTH_REFRESH_SKEW:
            if credentials.refresh_token is None:
                return self.payload(
                    provider_id=provider_id,
                    status=OAuthConnectionStatus.MISSING_REFRESH_TOKEN,
                    connected=False,
                    expires_at=credentials.expires_at,
                    refresh_required=False,
                    message="OAuth refresh token is missing",
                )
            return self._refresh_required_payload(
                provider_id=provider_id,
                expires_at=credentials.expires_at,
            )
        return self.payload(
            provider_id=provider_id,
            status=OAuthConnectionStatus.CONNECTED,
            connected=True,
            expires_at=credentials.expires_at,
            refresh_required=False,
            message=None,
        )

    def payload(
        self,
        provider_id: str,
        status: OAuthConnectionStatus,
        connected: bool,
        expires_at: datetime | None,
        refresh_required: bool,
        message: str | None,
    ) -> LibrarianOAuthStatusPayload:
        """Build one public OAuth status payload.

        Args:
            provider_id: Provider identifier.
            status: Public connection status.
            connected: Whether an access credential is usable.
            expires_at: Access token expiry when known.
            refresh_required: Whether the caller should refresh now.
            message: Optional user-facing status detail.

        Returns:
            Public OAuth status payload.
        """
        return LibrarianOAuthStatusPayload(
            provider_id=provider_id,
            status=status,
            connected=connected,
            expires_at=expires_at,
            refresh_required=refresh_required,
            reconnect_required=status
            in {
                OAuthConnectionStatus.EXPIRED,
                OAuthConnectionStatus.MISSING_REFRESH_TOKEN,
                OAuthConnectionStatus.NOT_CONNECTED,
            },
            next_action=(
                "poll"
                if status is OAuthConnectionStatus.PENDING
                else (
                    "refresh"
                    if refresh_required
                    else (
                        "start_oauth"
                        if status
                        in {
                            OAuthConnectionStatus.EXPIRED,
                            OAuthConnectionStatus.MISSING_REFRESH_TOKEN,
                            OAuthConnectionStatus.NOT_CONNECTED,
                        }
                        else "none"
                    )
                )
            ),
            message=message,
        )

    def _missing_expiry_payload(
        self,
        provider_id: str,
        refresh_token: str | None,
    ) -> LibrarianOAuthStatusPayload:
        """Execute missing expiry payload.

        Args:
            provider_id: Identifier for provider.
            refresh_token: Refresh token used by this operation.

        Returns:
            LibrarianOAuthStatusPayload result produced by missing expiry payload.
        """
        if refresh_token is None:
            return self.payload(
                provider_id=provider_id,
                status=OAuthConnectionStatus.EXPIRED,
                connected=False,
                expires_at=None,
                refresh_required=False,
                message="OAuth token expiry is missing",
            )
        return self._refresh_required_payload(
            provider_id=provider_id,
            expires_at=None,
        )

    def _refresh_required_payload(
        self,
        provider_id: str,
        expires_at: datetime | None,
    ) -> LibrarianOAuthStatusPayload:
        """Execute refresh required payload.

        Args:
            provider_id: Identifier for provider.
            expires_at: Expires at used by this operation.

        Returns:
            LibrarianOAuthStatusPayload result produced by refresh required payload.
        """
        return self.payload(
            provider_id=provider_id,
            status=OAuthConnectionStatus.REFRESH_REQUIRED,
            connected=True,
            expires_at=expires_at,
            refresh_required=True,
            message=None,
        )
