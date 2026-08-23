"""Application service for librarian OAuth provider lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.connections.application.librarians.oauth_client import OAuthProviderClient
from app.connections.application.librarians.oauth_connection_status_service import (
    LibrarianOAuthConnectionStatusService,
)
from app.connections.application.librarians.oauth_poll_result_handler import (
    LibrarianOAuthPollResultHandler,
)
from app.connections.application.librarians.oauth_secret_store import (
    DEVICE_FLOW_SECRET_KEYS,
    LibrarianOAuthSecretStore,
)
from app.connections.application.librarians.oauth_status_evaluator import (
    LibrarianOAuthStatusEvaluator,
)
from app.connections.domain.contracts.librarian_oauth_contracts import (
    OAuthPollResult,
)
from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import (
    AuthType,
    OAuthConnectionStatus,
    OAuthPollStatus,
    ProviderSecretKey,
    ProviderType,
)
from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.connections.domain.types.librarian_oauth_payload_types import (
    LibrarianOAuthStartPayload,
    LibrarianOAuthStatusPayload,
)
from app.shared.exceptions.common_exceptions import BoundaryValidationError
from app.shared.exceptions.connections_exceptions import (
    ConnectionsProviderUnsupportedError,
    ConnectionsResourceNotFoundError,
)
from app.shared.types.types_convert_utils import (
    aware_utc_datetime,
    enum_value,
    now_utc,
)


class LibrarianOAuthService:
    """Orchestrate OAuth lifecycle for Codex/GPT librarian providers.

    The five public use cases, provider eligibility check, and poll error guard
    remain together because they form one external OAuth state machine. Secret
    persistence, status policy, status queries, and poll result application are
    delegated to focused collaborators.
    """

    def __init__(
        self,
        provider_repo: ILibrarianProviderRepository,
        secret_repo: IProviderSecretRepository,
        oauth_client: OAuthProviderClient,
        now_provider: Callable[[], datetime] = now_utc,
    ) -> None:
        """Initialize OAuth service boundaries.

        Args:
            provider_repo: Provider metadata repository.
            secret_repo: Encrypted provider secret repository.
            oauth_client: External OAuth provider boundary.
            now_provider: Clock boundary for deterministic expiry tests.
        """
        self.provider_repo = provider_repo
        self.secret_repo = secret_repo
        self._secret_store = LibrarianOAuthSecretStore(secret_repo)
        self._status_evaluator = LibrarianOAuthStatusEvaluator()
        self._connection_status_service = LibrarianOAuthConnectionStatusService(
            secret_store=self._secret_store,
            evaluator=self._status_evaluator,
            now_provider=now_provider,
        )
        self._poll_result_handler = LibrarianOAuthPollResultHandler(
            secret_store=self._secret_store,
            evaluator=self._status_evaluator,
        )
        self.oauth_client = oauth_client
        self.now_provider = now_provider

    async def start_oauth(self, provider_id: str) -> LibrarianOAuthStartPayload:
        """Start a device OAuth flow for an OPENAI_CODEX provider.

        Args:
            provider_id: Provider id.

        Returns:
            LibrarianOAuthStartPayload: User-facing device authorization details.
        """
        provider = await self._load_codex_oauth_provider(provider_id)
        authorization = await self.oauth_client.start_device_authorization(provider)
        await self._secret_store.store_device_authorization(provider.id, authorization)
        payload = LibrarianOAuthStartPayload(
            provider_id=provider.id,
            status=OAuthPollStatus.PENDING,
            user_code=authorization.user_code,
            verification_uri=authorization.verification_uri,
            verification_uri_complete=authorization.verification_uri_complete,
            expires_at=authorization.expires_at,
            interval_seconds=authorization.interval_seconds,
        )
        return payload

    async def poll_oauth(self, provider_id: str) -> LibrarianOAuthStatusPayload:
        """Poll a pending OAuth device flow and persist tokens on success.

        Args:
            provider_id: Provider id.

        Returns:
            LibrarianOAuthStatusPayload: Public connection status.
        """
        provider = await self._load_codex_oauth_provider(provider_id)
        device_code = await self._secret_store.resolve(
            provider.id,
            ProviderSecretKey.OAUTH_DEVICE_CODE,
        )
        if device_code is None:
            raise ConnectionsProviderUnsupportedError(
                "OAuth device flow has not been started"
            )

        device_expires_at = await self._secret_store.expires_at(
            provider.id, ProviderSecretKey.OAUTH_DEVICE_EXPIRES_AT
        )
        if device_expires_at is not None and device_expires_at <= aware_utc_datetime(
            self.now_provider()
        ):
            await self._secret_store.delete(provider.id, DEVICE_FLOW_SECRET_KEYS)
            return self._status_evaluator.payload(
                provider_id=provider.id,
                status=OAuthConnectionStatus.EXPIRED,
                connected=False,
                expires_at=None,
                refresh_required=False,
                message="OAuth device flow expired",
            )

        poll_result = await self.oauth_client.poll_device_token(provider, device_code)
        payload = await self._handle_poll_result(provider, poll_result)
        return payload

    async def get_oauth_status(
        self,
        provider_id: str,
    ) -> LibrarianOAuthStatusPayload:
        """Return public OAuth connection state without token material.

        Args:
            provider_id: Provider id.

        Returns:
            LibrarianOAuthStatusPayload: Public connection status.
        """
        provider = await self._load_codex_oauth_provider(provider_id)
        payload = await self._connection_status_service.current_status(provider.id)
        return payload

    async def refresh_if_needed(
        self,
        provider_id: str,
    ) -> LibrarianOAuthStatusPayload:
        """Refresh a provider token only when it is missing or near expiry.

        Args:
            provider_id: Provider id.

        Returns:
            LibrarianOAuthStatusPayload: Public status after refresh evaluation.
        """
        provider = await self._load_codex_oauth_provider(provider_id)
        current_status = await self._connection_status_service.current_status(
            provider.id
        )
        if current_status["status"] is OAuthConnectionStatus.CONNECTED:
            return current_status

        if current_status["status"] not in {
            OAuthConnectionStatus.REFRESH_REQUIRED,
            OAuthConnectionStatus.EXPIRED,
            OAuthConnectionStatus.MISSING_REFRESH_TOKEN,
        }:
            return current_status

        refresh_token = await self._secret_store.resolve(
            provider.id,
            ProviderSecretKey.OAUTH_REFRESH_TOKEN,
        )
        if refresh_token is None:
            return self._status_evaluator.payload(
                provider_id=provider.id,
                status=OAuthConnectionStatus.MISSING_REFRESH_TOKEN,
                connected=False,
                expires_at=current_status["expires_at"],
                refresh_required=False,
                message="OAuth refresh token is missing",
            )

        token_set = await self.oauth_client.refresh_token(provider, refresh_token)
        await self._secret_store.store_token_set(provider.id, token_set)
        payload = self._status_evaluator.payload(
            provider_id=provider.id,
            status=OAuthConnectionStatus.CONNECTED,
            connected=True,
            expires_at=token_set.expires_at,
            refresh_required=False,
            message=None,
        )
        return payload

    async def delete_oauth_secrets(self, provider_id: str) -> None:
        """Delete all known provider credential keys.

        Args:
            provider_id: Provider id.

        Returns:
            None.
        """
        await self._secret_store.delete_all(provider_id)

    async def _load_codex_oauth_provider(self, provider_id: str) -> LibrarianProvider:
        """Load codex oauth provider.

        Args:
            provider_id: Identifier for provider.

        Returns:
            Loaded codex oauth provider.
        """
        row = await self.provider_repo.get(provider_id)
        if row is None:
            providers = await self.provider_repo.list_all()
            row = next(
                (provider for provider in providers if provider.name == provider_id),
                None,
            )
        if row is None:
            raise ConnectionsResourceNotFoundError(f"Provider not found: {provider_id}")

        try:
            provider_type = enum_value(
                row.provider_type,
                ProviderType,
                "provider_type",
            )
            auth_type = enum_value(row.auth_type, AuthType, "auth_type")
        except BoundaryValidationError as exc:
            raise ConnectionsProviderUnsupportedError(
                f"Provider type {row.provider_type} does not support OAuth lifecycle"
            ) from exc
        if (
            provider_type is not ProviderType.OPENAI_CODEX
            or auth_type is not AuthType.OAUTH
        ):
            raise ConnectionsProviderUnsupportedError(
                f"Provider type {provider_type.value} does not support OAuth lifecycle"
            )
        return row

    async def _handle_poll_result(
        self,
        provider: LibrarianProvider,
        poll_result: OAuthPollResult,
    ) -> LibrarianOAuthStatusPayload:
        """Handle poll result.

        Args:
            provider: Provider used by this operation.
            poll_result: Poll result used by this operation.

        Returns:
            LibrarianOAuthStatusPayload result produced by handle poll result.
        """
        if poll_result.status is OAuthPollStatus.CONNECTED:
            token_set = poll_result.token_set
            if token_set is None:
                raise ConnectionsProviderUnsupportedError(
                    "OAuth provider did not return tokens"
                )
        return await self._poll_result_handler.handle(
            provider_id=provider.id,
            poll_result=poll_result,
        )
