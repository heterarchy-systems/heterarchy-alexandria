"""Local operator approval and client-connection administration for MCP OAuth."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from http import HTTPStatus

from mcp.server.auth.provider import (
    construct_redirect_uri,
)

from app.mcp_server.local_oauth.contracts import (
    LocalMcpOAuthSettings,
    LocalOAuthAuthorizationRequestRecord,
    LocalOAuthClientConnectionRecord,
    LocalOAuthPairingCode,
)
from app.mcp_server.local_oauth.repository import LocalMcpOAuthRepository


@dataclass(frozen=True, slots=True)
class LocalOAuthApprovalError(Exception):
    """Safe approval failure without exposing operator credentials."""

    status_code: int
    detail: str


class LocalMcpOAuthApprovalService:
    """Own pairing-code approval and public-safe client connection operations."""

    def __init__(
        self, repository: LocalMcpOAuthRepository, settings: LocalMcpOAuthSettings
    ) -> None:
        """Initialize approval state dependencies.

        Args:
            repository: Durable local OAuth aggregate repository.
            settings: Local approval and token lifetime policy.
        """
        self._repository = repository
        self._settings = settings

    async def list_client_connections(
        self,
    ) -> tuple[LocalOAuthClientConnectionRecord, ...]:
        """List OAuth MCP clients for the local operator without token material.

        Returns:
            Public-safe registered client connection records.
        """
        return await self._repository.list_client_connections(current_epoch_seconds())

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
        if await self._repository.get_client(client_id) is None:
            return None
        now = current_epoch_seconds()
        extended_count = await self._repository.extend_client_refresh_tokens(
            client_id=client_id,
            extension_seconds=self._settings.refresh_token_ttl_seconds,
            now=now,
        )
        if extended_count == 0:
            return None
        return await self._client_connection(client_id)

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
        return await self._repository.delete_client(client_id)

    async def pending_authorization(
        self,
        request_id: str,
    ) -> LocalOAuthAuthorizationRequestRecord:
        """Return one valid approval request for the local browser screen.

        Args:
            request_id: Value supplied to pending_authorization.
        Returns:
            LocalOAuthAuthorizationRequestRecord: Value produced by pending_authorization."""
        record = await self._repository.get_authorization_request(request_id)
        now = current_epoch_seconds()
        if record is None or record.consumed_at is not None or record.expires_at <= now:
            raise LocalOAuthApprovalError(
                HTTPStatus.BAD_REQUEST,
                "OAuth approval request is invalid or expired",
            )
        if record.approval_attempts >= self._settings.max_approval_attempts:
            raise LocalOAuthApprovalError(
                HTTPStatus.TOO_MANY_REQUESTS,
                "OAuth approval request is locked",
            )
        return record

    async def create_pairing_code(self) -> LocalOAuthPairingCode:
        """Create one short-lived code without exposing OAuth bearer tokens.

        Returns:
            Newly generated single-use pairing code and expiry epoch.
        """
        code = _pairing_code()
        now = current_epoch_seconds()
        expires_at = now + self._settings.pairing_code_ttl_seconds
        await self._repository.create_pairing_code(
            code_hash=hash_opaque_value(code),
            expires_at=expires_at,
            now=now,
        )
        return LocalOAuthPairingCode(code=code, expires_at=expires_at)

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
        record = await self.pending_authorization(request_id)
        pairing_code_hash = self._pairing_code_hash(approval_code)
        code = new_opaque_value()
        now = current_epoch_seconds()
        issued = await self._repository.approve_authorization_request(
            request_id=request_id,
            code=code,
            code_hash=hash_opaque_value(code),
            code_expires_at=now + self._settings.authorization_code_ttl_seconds,
            now=now,
            pairing_code_hash=pairing_code_hash,
        )
        if issued is None:
            await self._raise_failed_approval(request_id)
        return construct_redirect_uri(
            record.redirect_uri,
            code=code,
            state=record.state,
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
        record = await self.pending_authorization(request_id)
        denied = await self._repository.deny_authorization_request(
            request_id,
            current_epoch_seconds(),
            pairing_code_hash=self._pairing_code_hash(approval_code),
        )
        if not denied:
            await self._raise_failed_approval(request_id)
        return construct_redirect_uri(
            record.redirect_uri,
            error="access_denied",
            error_description="Local operator denied MCP access",
            state=record.state,
        )

    def _pairing_code_hash(self, approval_code: str) -> str | None:
        """Execute pairing code hash.

        Args:
            approval_code: Approval code used by this operation.

        Returns:
            str | None result produced by pairing code hash.
        """
        if hmac.compare_digest(
            approval_code.encode("utf-8"),
            self._settings.approval_key.encode("utf-8"),
        ):
            return None
        return hash_opaque_value(_normalize_pairing_code(approval_code))

    async def _raise_failed_approval(self, request_id: str) -> None:
        """Execute raise failed approval.

        Args:
            request_id: Identifier for request.
        """
        attempts = await self._repository.record_failed_approval(
            request_id, current_epoch_seconds()
        )
        if attempts == 0:
            raise LocalOAuthApprovalError(
                HTTPStatus.BAD_REQUEST,
                "OAuth approval request is no longer available",
            )
        if attempts >= self._settings.max_approval_attempts:
            raise LocalOAuthApprovalError(
                HTTPStatus.TOO_MANY_REQUESTS,
                "OAuth approval request is locked",
            )
        raise LocalOAuthApprovalError(
            HTTPStatus.FORBIDDEN,
            "OAuth pairing code is invalid",
        )

    async def _client_connection(
        self,
        client_id: str,
    ) -> LocalOAuthClientConnectionRecord | None:
        """Execute client connection.

        Args:
            client_id: Identifier for client.

        Returns:
            LocalOAuthClientConnectionRecord | None result produced by client connection.
        """
        for connection in await self.list_client_connections():
            if connection.client_id == client_id:
                return connection
        return None


def new_opaque_value() -> str:
    """Create a new opaque approval value.

    Returns:
        New opaque approval value.
    """
    return secrets.token_urlsafe(32)


def _pairing_code() -> str:
    """Execute pairing code.

    Returns:
        str result produced by pairing code.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    compact = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{compact[:4]}-{compact[4:]}"


def _normalize_pairing_code(value: str) -> str:
    """Normalize pairing code.

    Args:
        value: Value being processed.

    Returns:
        Normalized pairing code.
    """
    compact = "".join(character for character in value.upper() if character.isalnum())
    if len(compact) != 8:
        return compact
    return f"{compact[:4]}-{compact[4:]}"


def hash_opaque_value(value: str) -> str:
    """Hash an opaque approval value.

    Args:
        value: Value to transform.

    Returns:
        Stable hash of the opaque approval value.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def current_epoch_seconds() -> int:
    """Return the current Unix epoch time in seconds.

    Returns:
        Current Unix epoch time in seconds.
    """
    return int(time.time())
