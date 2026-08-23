"""Transactional repository for local MCP OAuth state."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.mcp_server.local_oauth.contracts import (
    LocalOAuthAuthorizationCodeRecord,
    LocalOAuthAuthorizationRequestRecord,
    LocalOAuthClientRecord,
)
from app.mcp_server.local_oauth.orm import (
    McpOAuthAuthorizationCodeORM,
    McpOAuthAuthorizationRequestORM,
    McpOAuthClientORM,
    McpOAuthPairingCodeORM,
    McpOAuthTokenORM,
)
from app.mcp_server.local_oauth.persistence.local_oauth_grant_repository import (
    LocalOAuthGrantRepository,
)
from app.shared.types.extra_types import JSONObject, JSONValue


class LocalMcpOAuthRepository(LocalOAuthGrantRepository):
    """Persist one OAuth transaction aggregate with atomic consume/rotation steps.

    The public method count is intentionally above the normal review threshold because
    client registration, authorization codes, and token families must share one
    database transaction boundary to prevent replay and partial token issuance.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Create the OAuth repository.

        Args:
            session_factory: Async SQLAlchemy session factory.
        """
        super().__init__(session_factory)
        self._session_factory = session_factory

    async def save_client(
        self,
        client_id: str,
        client_secret_ciphertext: str | None,
        metadata: JSONObject,
        issued_at: int,
        secret_expires_at: int | None,
    ) -> None:
        """Persist one dynamic OAuth client registration.

        Args:
            client_id: Value supplied to save_client.
            client_secret_ciphertext: Value supplied to save_client.
            metadata: Value supplied to save_client.
            issued_at: Value supplied to save_client.
            secret_expires_at: Value supplied to save_client."""
        async with self._session_factory() as session, session.begin():
            session.add(
                McpOAuthClientORM(
                    client_id=client_id,
                    client_secret_ciphertext=client_secret_ciphertext,
                    client_metadata=metadata,
                    issued_at=issued_at,
                    secret_expires_at=secret_expires_at,
                )
            )

    async def get_client(self, client_id: str) -> LocalOAuthClientRecord | None:
        """Load one dynamic OAuth client registration.

        Args:
            client_id: Value supplied to get_client.
        Returns:
            LocalOAuthClientRecord | None: Value produced by get_client."""
        async with self._session_factory() as session:
            row = await session.get(McpOAuthClientORM, client_id)
        if row is None:
            return None
        return LocalOAuthClientRecord(
            client_id=row.client_id,
            client_secret_ciphertext=row.client_secret_ciphertext,
            metadata=_frozen_mapping(row.client_metadata),
            issued_at=row.issued_at,
            secret_expires_at=row.secret_expires_at,
        )

    async def create_authorization_request(
        self,
        record: LocalOAuthAuthorizationRequestRecord,
    ) -> None:
        """Persist one pending operator approval request.

        Args:
            record: Value supplied to create_authorization_request."""
        async with self._session_factory() as session, session.begin():
            session.add(
                McpOAuthAuthorizationRequestORM(
                    request_id=record.request_id,
                    client_id=record.client_id,
                    client_name=record.client_name,
                    state=record.state,
                    scopes=list(record.scopes),
                    code_challenge=record.code_challenge,
                    redirect_uri=record.redirect_uri,
                    redirect_uri_provided_explicitly=(
                        record.redirect_uri_provided_explicitly
                    ),
                    resource=record.resource,
                    expires_at=record.expires_at,
                    approval_attempts=record.approval_attempts,
                    consumed_at=record.consumed_at,
                )
            )

    async def get_authorization_request(
        self,
        request_id: str,
    ) -> LocalOAuthAuthorizationRequestRecord | None:
        """Load one pending operator approval request.

        Args:
            request_id: Value supplied to get_authorization_request.
        Returns:
            LocalOAuthAuthorizationRequestRecord | None: Value produced by get_authorization_request."""
        async with self._session_factory() as session:
            row = await session.get(McpOAuthAuthorizationRequestORM, request_id)
        return None if row is None else _authorization_request_record(row)

    async def record_failed_approval(self, request_id: str, now: int) -> int:
        """Increment a pending request's failed approval attempts.

        Args:
            request_id: Value supplied to record_failed_approval.
            now: Value supplied to record_failed_approval.
        Returns:
            int: Value produced by record_failed_approval."""
        async with self._session_factory() as session, session.begin():
            row = await session.get(McpOAuthAuthorizationRequestORM, request_id)
            if row is None or row.consumed_at is not None or row.expires_at <= now:
                return 0
            row.approval_attempts += 1
            return row.approval_attempts

    async def create_pairing_code(
        self,
        code_hash: str,
        expires_at: int,
        now: int,
    ) -> None:
        """Replace prior active pairing codes with one new hashed code.

        Args:
            code_hash: SHA-256 lookup value for the code.
            expires_at: Pairing-code expiry epoch.
            now: Current epoch.
        """
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(McpOAuthPairingCodeORM)
                .where(McpOAuthPairingCodeORM.consumed_at.is_(None))
                .values(consumed_at=now)
            )
            session.add(
                McpOAuthPairingCodeORM(
                    code_hash=code_hash,
                    expires_at=expires_at,
                    consumed_at=None,
                    created_at=now,
                )
            )

    async def approve_authorization_request(
        self,
        request_id: str,
        code: str,
        code_hash: str,
        code_expires_at: int,
        now: int,
        pairing_code_hash: str | None = None,
    ) -> LocalOAuthAuthorizationCodeRecord | None:
        """Consume one approval request and atomically create its code.

        Args:
            request_id: Value supplied to approve_authorization_request.
            code: Value supplied to approve_authorization_request.
            code_hash: Value supplied to approve_authorization_request.
            code_expires_at: Value supplied to approve_authorization_request.
            now: Value supplied to approve_authorization_request.
            pairing_code_hash: Pairing code hash used by this operation.
        Returns:
            LocalOAuthAuthorizationCodeRecord | None: Value produced by approve_authorization_request.
        """
        async with self._session_factory() as session, session.begin():
            request_row = await session.get(
                McpOAuthAuthorizationRequestORM,
                request_id,
            )
            if (
                request_row is None
                or request_row.consumed_at is not None
                or request_row.expires_at <= now
            ):
                return None
            if pairing_code_hash is not None:
                pairing_row = await session.get(
                    McpOAuthPairingCodeORM,
                    pairing_code_hash,
                )
                if (
                    pairing_row is None
                    or pairing_row.consumed_at is not None
                    or pairing_row.expires_at <= now
                ):
                    return None
                pairing_row.consumed_at = now
            request_row.consumed_at = now
            session.add(
                McpOAuthAuthorizationCodeORM(
                    code_hash=code_hash,
                    client_id=request_row.client_id,
                    scopes=list(request_row.scopes),
                    code_challenge=request_row.code_challenge,
                    redirect_uri=request_row.redirect_uri,
                    redirect_uri_provided_explicitly=(
                        request_row.redirect_uri_provided_explicitly
                    ),
                    resource=request_row.resource,
                    expires_at=code_expires_at,
                    consumed_at=None,
                )
            )
            return LocalOAuthAuthorizationCodeRecord(
                code=code,
                client_id=request_row.client_id,
                scopes=tuple(request_row.scopes),
                code_challenge=request_row.code_challenge,
                redirect_uri=request_row.redirect_uri,
                redirect_uri_provided_explicitly=(
                    request_row.redirect_uri_provided_explicitly
                ),
                resource=request_row.resource,
                expires_at=code_expires_at,
            )

    async def deny_authorization_request(
        self,
        request_id: str,
        now: int,
        pairing_code_hash: str | None = None,
    ) -> bool:
        """Consume one pending request without issuing a code.

        Args:
            request_id: Value supplied to deny_authorization_request.
            now: Value supplied to deny_authorization_request.
            pairing_code_hash: Pairing code hash used by this operation.
        Returns:
            bool: Value produced by deny_authorization_request.
        """
        async with self._session_factory() as session, session.begin():
            row = await session.get(McpOAuthAuthorizationRequestORM, request_id)
            if row is None or row.consumed_at is not None or row.expires_at <= now:
                return False
            if pairing_code_hash is not None:
                pairing_row = await session.get(
                    McpOAuthPairingCodeORM,
                    pairing_code_hash,
                )
                if (
                    pairing_row is None
                    or pairing_row.consumed_at is not None
                    or pairing_row.expires_at <= now
                ):
                    return False
                pairing_row.consumed_at = now
            row.consumed_at = now
            return True

    async def delete_client(self, client_id: str) -> bool:
        """Hard-delete one OAuth client aggregate.

        Args:
            client_id: Registered OAuth client id.

        Returns:
            Whether a client registration row was removed.
        """
        async with self._session_factory() as session, session.begin():
            row = await session.get(McpOAuthClientORM, client_id)
            if row is None:
                return False
            for child_model in (
                McpOAuthAuthorizationRequestORM,
                McpOAuthAuthorizationCodeORM,
                McpOAuthTokenORM,
            ):
                await session.execute(
                    delete(child_model).where(child_model.client_id == client_id)
                )
            await session.delete(row)
            return True


def _authorization_request_record(
    row: McpOAuthAuthorizationRequestORM,
) -> LocalOAuthAuthorizationRequestRecord:
    """Execute authorization request record.

    Args:
        row: Row used by this operation.

    Returns:
        LocalOAuthAuthorizationRequestRecord result produced by authorization request record.
    """
    return LocalOAuthAuthorizationRequestRecord(
        request_id=row.request_id,
        client_id=row.client_id,
        client_name=row.client_name,
        state=row.state,
        scopes=tuple(row.scopes),
        code_challenge=row.code_challenge,
        redirect_uri=row.redirect_uri,
        redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
        resource=row.resource,
        expires_at=row.expires_at,
        approval_attempts=row.approval_attempts,
        consumed_at=row.consumed_at,
    )


def _frozen_mapping(value: JSONObject) -> Mapping[str, JSONValue]:
    """Execute frozen mapping.

    Args:
        value: Value being processed.

    Returns:
        Mapping[str, JSONValue] result produced by frozen mapping.
    """
    return MappingProxyType(dict(value))
