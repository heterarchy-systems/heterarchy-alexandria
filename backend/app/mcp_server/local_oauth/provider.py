"""Self-hosted OAuth authorization provider for the MCP HTTP endpoint."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import TypeAdapter

from app.mcp_server.local_oauth.contracts import (
    LocalMcpOAuthSettings,
    LocalOAuthAuthorizationRequestRecord,
    LocalOAuthClientConnectionRecord,
    LocalOAuthPairingCode,
)
from app.mcp_server.local_oauth.local_oauth_enums import LocalOAuthTokenKind
from app.mcp_server.local_oauth.provider_approval import (
    LocalMcpOAuthApprovalService,
    current_epoch_seconds,
    hash_opaque_value,
    new_opaque_value,
)
from app.mcp_server.local_oauth.repository import LocalMcpOAuthRepository
from app.shared.security.secret_cipher import SecretCipher
from app.shared.types.extra_types import JSONObject

_JSON_OBJECT_ADAPTER = TypeAdapter(JSONObject)


class LocalMcpOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """Issue, rotate, verify, and revoke opaque MCP OAuth credentials.

    The public method count mirrors the MCP SDK provider protocol plus the local
    approval use case. Persistence and cryptographic storage remain delegated to
    focused collaborators.
    """

    def __init__(
        self,
        repository: LocalMcpOAuthRepository,
        secret_cipher: SecretCipher,
        settings: LocalMcpOAuthSettings,
    ) -> None:
        """Create the local OAuth provider.

        Args:
            repository: Durable OAuth state repository.
            secret_cipher: AES-GCM cipher for dynamic client secrets.
            settings: OAuth endpoint and expiry policy.
        """
        self._repository = repository
        self._secret_cipher = secret_cipher
        self._settings = settings
        self._approval_service = LocalMcpOAuthApprovalService(
            repository=repository,
            settings=settings,
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Load one registered OAuth client.

        Args:
            client_id: Value supplied to get_client.
        Returns:
            OAuthClientInformationFull | None: Value produced by get_client."""
        record = await self._repository.get_client(client_id)
        if record is None:
            return None
        payload = dict(record.metadata)
        payload.update(
            {
                "client_id": record.client_id,
                "client_secret": (
                    None
                    if record.client_secret_ciphertext is None
                    else self._secret_cipher.decrypt(record.client_secret_ciphertext)
                ),
                "client_id_issued_at": record.issued_at,
                "client_secret_expires_at": record.secret_expires_at,
            }
        )
        return OAuthClientInformationFull.model_validate(payload)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Persist one SDK-validated dynamic client registration.

        Args:
            client_info: Value supplied to register_client."""
        client_id = client_info.client_id
        if client_id is None:
            raise ValueError("OAuth client registration requires client_id")
        metadata = _JSON_OBJECT_ADAPTER.validate_python(
            client_info.model_dump(
                mode="json",
                exclude={
                    "client_id",
                    "client_secret",
                    "client_id_issued_at",
                    "client_secret_expires_at",
                },
            )
        )
        encrypted_secret = (
            None
            if client_info.client_secret is None
            else self._secret_cipher.encrypt(client_info.client_secret)
        )
        await self._repository.save_client(
            client_id=client_id,
            client_secret_ciphertext=encrypted_secret,
            metadata=metadata,
            issued_at=client_info.client_id_issued_at or current_epoch_seconds(),
            secret_expires_at=client_info.client_secret_expires_at,
        )

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Create a pending local approval request and return its browser URL.

        Args:
            client: Value supplied to authorize.
            params: Value supplied to authorize.
        Returns:
            str: Value produced by authorize."""
        client_id = client.client_id
        if client_id is None:
            raise AuthorizeError("unauthorized_client", "OAuth client is missing id")
        resource = params.resource or self._settings.resource_url
        if resource != self._settings.resource_url:
            raise AuthorizeError(
                "invalid_request",
                "OAuth resource does not match the Alexandria MCP endpoint",
            )
        scopes = tuple(params.scopes or self._settings.default_scopes)
        if not set(self._settings.required_scopes).issubset(scopes):
            raise AuthorizeError(
                "invalid_scope",
                "OAuth request is missing required Alexandria MCP scopes",
            )
        now = current_epoch_seconds()
        request_id = new_opaque_value()
        await self._repository.create_authorization_request(
            LocalOAuthAuthorizationRequestRecord(
                request_id=request_id,
                client_id=client_id,
                client_name=client.client_name,
                state=params.state,
                scopes=scopes,
                code_challenge=params.code_challenge,
                redirect_uri=str(params.redirect_uri),
                redirect_uri_provided_explicitly=(
                    params.redirect_uri_provided_explicitly
                ),
                resource=resource,
                expires_at=now + self._settings.approval_ttl_seconds,
                approval_attempts=0,
                consumed_at=None,
            )
        )
        query = urlencode({"request_id": request_id})
        return f"{self._settings.issuer_url.rstrip('/')}/approve?{query}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        """Load one unconsumed authorization code for SDK PKCE validation.

        Args:
            client: Value supplied to load_authorization_code.
            authorization_code: Value supplied to load_authorization_code.
        Returns:
            AuthorizationCode | None: Value produced by load_authorization_code."""
        record = await self._repository.get_authorization_code(
            raw_code=authorization_code,
            code_hash=hash_opaque_value(authorization_code),
            now=current_epoch_seconds(),
        )
        if record is None or record.client_id != client.client_id:
            return None
        return AuthorizationCode(
            code=record.code,
            scopes=list(record.scopes),
            expires_at=record.expires_at,
            client_id=record.client_id,
            code_challenge=record.code_challenge,
            redirect_uri=record.redirect_uri,
            redirect_uri_provided_explicitly=(record.redirect_uri_provided_explicitly),
            resource=record.resource,
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        """Consume one code and atomically issue an access/refresh pair.

        Args:
            client: Value supplied to exchange_authorization_code.
            authorization_code: Value supplied to exchange_authorization_code.
        Returns:
            OAuthToken: Value produced by exchange_authorization_code."""
        if authorization_code.client_id != client.client_id:
            raise TokenError("invalid_grant", "authorization code client mismatch")
        access_token = new_opaque_value()
        refresh_token = new_opaque_value()
        now = current_epoch_seconds()
        exchanged = await self._repository.exchange_authorization_code(
            code_hash=hash_opaque_value(authorization_code.code),
            access_token_hash=hash_opaque_value(access_token),
            refresh_token_hash=hash_opaque_value(refresh_token),
            family_id=secrets.token_hex(32),
            access_expires_at=now + self._settings.access_token_ttl_seconds,
            refresh_expires_at=now + self._settings.refresh_token_ttl_seconds,
            now=now,
        )
        if exchanged is None:
            raise TokenError("invalid_grant", "authorization code is unavailable")
        return OAuthToken(
            access_token=access_token,
            expires_in=self._settings.access_token_ttl_seconds,
            scope=" ".join(exchanged.scopes),
            refresh_token=refresh_token,
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        """Load one active refresh token by opaque value.

        Args:
            client: Value supplied to load_refresh_token.
            refresh_token: Value supplied to load_refresh_token.
        Returns:
            RefreshToken | None: Value produced by load_refresh_token."""
        record = await self._repository.get_token(
            raw_token=refresh_token,
            token_hash=hash_opaque_value(refresh_token),
            token_kind=LocalOAuthTokenKind.REFRESH,
            now=current_epoch_seconds(),
        )
        if record is None or record.client_id != client.client_id:
            return None
        return RefreshToken(
            token=record.token,
            client_id=record.client_id,
            scopes=list(record.scopes),
            expires_at=record.expires_at,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Rotate one refresh-token family and issue a replacement pair.

        Args:
            client: Value supplied to exchange_refresh_token.
            refresh_token: Value supplied to exchange_refresh_token.
            scopes: Value supplied to exchange_refresh_token.
        Returns:
            OAuthToken: Value produced by exchange_refresh_token."""
        if refresh_token.client_id != client.client_id:
            raise TokenError("invalid_grant", "refresh token client mismatch")
        next_access = new_opaque_value()
        next_refresh = new_opaque_value()
        now = current_epoch_seconds()
        rotated = await self._repository.rotate_refresh_token(
            old_refresh_hash=hash_opaque_value(refresh_token.token),
            access_token_hash=hash_opaque_value(next_access),
            refresh_token_hash=hash_opaque_value(next_refresh),
            scopes=tuple(scopes),
            access_expires_at=now + self._settings.access_token_ttl_seconds,
            refresh_expires_at=now + self._settings.refresh_token_ttl_seconds,
            now=now,
        )
        if rotated is None:
            raise TokenError("invalid_grant", "refresh token is unavailable")
        return OAuthToken(
            access_token=next_access,
            expires_in=self._settings.access_token_ttl_seconds,
            scope=" ".join(rotated.scopes),
            refresh_token=next_refresh,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Verify one opaque bearer token against the durable token store.

        Args:
            token: Value supplied to load_access_token.
        Returns:
            AccessToken | None: Value produced by load_access_token."""
        record = await self._repository.get_token(
            raw_token=token,
            token_hash=hash_opaque_value(token),
            token_kind=LocalOAuthTokenKind.ACCESS,
            now=current_epoch_seconds(),
        )
        if record is None:
            return None
        return AccessToken(
            token=record.token,
            client_id=record.client_id,
            scopes=list(record.scopes),
            expires_at=record.expires_at,
            resource=record.resource,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revoke the complete access/refresh family for one opaque token.

        Args:
            token: Value supplied to revoke_token."""
        await self._repository.revoke_token_family(
            hash_opaque_value(token.token),
            current_epoch_seconds(),
        )

    async def list_client_connections(
        self,
    ) -> tuple[LocalOAuthClientConnectionRecord, ...]:
        """List OAuth MCP clients for the local operator without token material.

        Returns:
            Public-safe registered client connection records.
        """
        return await self._approval_service.list_client_connections()

    async def extend_client_connection(
        self,
        client_id: str,
    ) -> LocalOAuthClientConnectionRecord | None:
        """Extend one currently connected MCP client's refresh-token window.

        Args:
            client_id: Registered OAuth client id.

        Returns:
            Updated connection record, or None when the client is unknown or expired.
        """
        return await self._approval_service.extend_client_connection(client_id)

    async def delete_client_connection(
        self,
        client_id: str,
    ) -> bool:
        """Hard-delete one MCP OAuth client and all credential state.

        Args:
            client_id: Registered OAuth client id.

        Returns:
            Whether the client aggregate existed and was deleted.
        """
        return await self._approval_service.delete_client_connection(client_id)

    async def pending_authorization(
        self,
        request_id: str,
    ) -> LocalOAuthAuthorizationRequestRecord:
        """Return one valid approval request for the local browser screen.

        Args:
            request_id: Value supplied to pending_authorization.
        Returns:
            LocalOAuthAuthorizationRequestRecord: Value produced by pending_authorization."""
        return await self._approval_service.pending_authorization(request_id)

    async def create_pairing_code(self) -> LocalOAuthPairingCode:
        """Create one short-lived code without exposing OAuth bearer tokens.

        Returns:
            Newly generated single-use pairing code and expiry epoch.
        """
        return await self._approval_service.create_pairing_code()

    async def approve_authorization(
        self,
        request_id: str,
        approval_code: str,
    ) -> str:
        """Approve one request with a single-use code or bootstrap operator key.

        Args:
            request_id: Value supplied to approve_authorization.
            approval_code: One-time pairing code or bootstrap operator key.
        Returns:
            str: Value produced by approve_authorization."""
        return await self._approval_service.approve_authorization(
            request_id, approval_code
        )

    async def deny_authorization(
        self,
        request_id: str,
        approval_code: str,
    ) -> str:
        """Deny one request with a single-use code or bootstrap operator key.

        Args:
            request_id: Value supplied to deny_authorization.
            approval_code: One-time pairing code or bootstrap operator key.
        Returns:
            str: Value produced by deny_authorization."""
        return await self._approval_service.deny_authorization(
            request_id, approval_code
        )
