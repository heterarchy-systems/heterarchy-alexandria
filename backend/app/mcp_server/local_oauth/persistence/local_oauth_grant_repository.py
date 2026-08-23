"""Focused persistence for local MCP OAuth grant and token lifecycle."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.mcp_server.local_oauth.contracts import (
    LocalOAuthAuthorizationCodeRecord,
    LocalOAuthClientConnectionRecord,
    LocalOAuthTokenRecord,
)
from app.mcp_server.local_oauth.local_oauth_enums import (
    LocalOAuthClientConnectionStatus,
    LocalOAuthTokenKind,
)
from app.mcp_server.local_oauth.orm import (
    McpOAuthAuthorizationCodeORM,
    McpOAuthClientORM,
    McpOAuthTokenORM,
)
from app.shared.types.extra_types import JSONObject


class LocalOAuthGrantRepository:
    """Persist OAuth authorization-code and token-family lifecycle state."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Create the OAuth repository.

        Args:
            session_factory: Async SQLAlchemy session factory.
        """
        self._session_factory = session_factory

    async def list_client_connections(
        self,
        now: int,
    ) -> tuple[LocalOAuthClientConnectionRecord, ...]:
        """List registered MCP OAuth clients with public-safe token status.

        Args:
            now: Current epoch used to classify token expiry.

        Returns:
            Operator-visible client connection records without token material.
        """
        async with self._session_factory() as session:
            client_rows = tuple(
                (await session.execute(select(McpOAuthClientORM))).scalars().all()
            )
            token_rows = tuple(
                (await session.execute(select(McpOAuthTokenORM))).scalars().all()
            )
        return tuple(
            _client_connection_record(
                client_row=client_row,
                token_rows=tuple(
                    token_row
                    for token_row in token_rows
                    if token_row.client_id == client_row.client_id
                ),
                now=now,
            )
            for client_row in client_rows
        )

    async def get_authorization_code(
        self,
        raw_code: str,
        code_hash: str,
        now: int,
    ) -> LocalOAuthAuthorizationCodeRecord | None:
        """Load one active authorization code by its hashed lookup key.

        Args:
            raw_code: Value supplied to get_authorization_code.
            code_hash: Value supplied to get_authorization_code.
            now: Value supplied to get_authorization_code.
        Returns:
            LocalOAuthAuthorizationCodeRecord | None: Value produced by get_authorization_code."""
        async with self._session_factory() as session:
            row = await session.get(McpOAuthAuthorizationCodeORM, code_hash)
        if row is None or row.consumed_at is not None or row.expires_at <= now:
            return None
        return LocalOAuthAuthorizationCodeRecord(
            code=raw_code,
            client_id=row.client_id,
            scopes=tuple(row.scopes),
            code_challenge=row.code_challenge,
            redirect_uri=row.redirect_uri,
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
            resource=row.resource,
            expires_at=row.expires_at,
        )

    async def exchange_authorization_code(
        self,
        code_hash: str,
        access_token_hash: str,
        refresh_token_hash: str,
        family_id: str,
        access_expires_at: int,
        refresh_expires_at: int,
        now: int,
    ) -> LocalOAuthAuthorizationCodeRecord | None:
        """Consume a code and atomically persist its access/refresh token pair.

        Args:
            code_hash: Value supplied to exchange_authorization_code.
            access_token_hash: Value supplied to exchange_authorization_code.
            refresh_token_hash: Value supplied to exchange_authorization_code.
            family_id: Value supplied to exchange_authorization_code.
            access_expires_at: Value supplied to exchange_authorization_code.
            refresh_expires_at: Value supplied to exchange_authorization_code.
            now: Value supplied to exchange_authorization_code.
        Returns:
            LocalOAuthAuthorizationCodeRecord | None: Value produced by exchange_authorization_code."""
        async with self._session_factory() as session, session.begin():
            row = await session.get(McpOAuthAuthorizationCodeORM, code_hash)
            if row is None or row.consumed_at is not None or row.expires_at <= now:
                return None
            row.consumed_at = now
            _add_token_pair(
                session,
                client_id=row.client_id,
                scopes=row.scopes,
                resource=row.resource,
                family_id=family_id,
                access_token_hash=access_token_hash,
                refresh_token_hash=refresh_token_hash,
                access_expires_at=access_expires_at,
                refresh_expires_at=refresh_expires_at,
                now=now,
            )
            return LocalOAuthAuthorizationCodeRecord(
                code="",
                client_id=row.client_id,
                scopes=tuple(row.scopes),
                code_challenge=row.code_challenge,
                redirect_uri=row.redirect_uri,
                redirect_uri_provided_explicitly=(row.redirect_uri_provided_explicitly),
                resource=row.resource,
                expires_at=row.expires_at,
            )

    async def get_token(
        self,
        raw_token: str,
        token_hash: str,
        token_kind: LocalOAuthTokenKind,
        now: int,
    ) -> LocalOAuthTokenRecord | None:
        """Load one active opaque token by its hashed lookup key.

        Args:
            raw_token: Value supplied to get_token.
            token_hash: Value supplied to get_token.
            token_kind: Value supplied to get_token.
            now: Value supplied to get_token.
        Returns:
            LocalOAuthTokenRecord | None: Value produced by get_token."""
        async with self._session_factory() as session:
            row = await session.get(McpOAuthTokenORM, token_hash)
        if (
            row is None
            or row.token_kind != token_kind.value
            or row.revoked_at is not None
            or row.expires_at <= now
        ):
            return None
        return LocalOAuthTokenRecord(
            token=raw_token,
            token_kind=token_kind,
            family_id=row.family_id,
            client_id=row.client_id,
            scopes=tuple(row.scopes),
            resource=row.resource,
            expires_at=row.expires_at,
        )

    async def rotate_refresh_token(
        self,
        old_refresh_hash: str,
        access_token_hash: str,
        refresh_token_hash: str,
        scopes: tuple[str, ...],
        access_expires_at: int,
        refresh_expires_at: int,
        now: int,
    ) -> LocalOAuthTokenRecord | None:
        """Revoke one token family and atomically issue its rotated pair.

        Args:
            old_refresh_hash: Value supplied to rotate_refresh_token.
            access_token_hash: Value supplied to rotate_refresh_token.
            refresh_token_hash: Value supplied to rotate_refresh_token.
            scopes: Value supplied to rotate_refresh_token.
            access_expires_at: Value supplied to rotate_refresh_token.
            refresh_expires_at: Value supplied to rotate_refresh_token.
            now: Value supplied to rotate_refresh_token.
        Returns:
            LocalOAuthTokenRecord | None: Value produced by rotate_refresh_token."""
        async with self._session_factory() as session, session.begin():
            old_row = await session.get(McpOAuthTokenORM, old_refresh_hash)
            if (
                old_row is None
                or old_row.token_kind != LocalOAuthTokenKind.REFRESH.value
                or old_row.revoked_at is not None
                or old_row.expires_at <= now
                or not set(scopes).issubset(set(old_row.scopes))
            ):
                return None
            await session.execute(
                update(McpOAuthTokenORM)
                .where(
                    McpOAuthTokenORM.family_id == old_row.family_id,
                    McpOAuthTokenORM.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            _add_token_pair(
                session,
                client_id=old_row.client_id,
                scopes=list(scopes),
                resource=old_row.resource,
                family_id=old_row.family_id,
                access_token_hash=access_token_hash,
                refresh_token_hash=refresh_token_hash,
                access_expires_at=access_expires_at,
                refresh_expires_at=refresh_expires_at,
                now=now,
            )
            return LocalOAuthTokenRecord(
                token="",
                token_kind=LocalOAuthTokenKind.REFRESH,
                family_id=old_row.family_id,
                client_id=old_row.client_id,
                scopes=scopes,
                resource=old_row.resource,
                expires_at=refresh_expires_at,
            )

    async def revoke_token_family(self, token_hash: str, now: int) -> None:
        """Revoke both access and refresh tokens belonging to one family.

        Args:
            token_hash: Value supplied to revoke_token_family.
            now: Value supplied to revoke_token_family."""
        async with self._session_factory() as session, session.begin():
            row = await session.get(McpOAuthTokenORM, token_hash)
            if row is None:
                return
            await session.execute(
                update(McpOAuthTokenORM)
                .where(
                    McpOAuthTokenORM.family_id == row.family_id,
                    McpOAuthTokenORM.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )

    async def extend_client_refresh_tokens(
        self,
        client_id: str,
        extension_seconds: int,
        now: int,
    ) -> int:
        """Extend currently connected refresh tokens from their current expiry.

        Args:
            client_id: Registered OAuth client id.
            extension_seconds: Duration added to each active refresh-token expiry.
            now: Current epoch; expired refresh tokens require reconnect.

        Returns:
            Number of refresh-token rows extended.
        """
        async with self._session_factory() as session, session.begin():
            rows = tuple(
                (
                    await session.execute(
                        select(McpOAuthTokenORM).where(
                            McpOAuthTokenORM.client_id == client_id,
                            McpOAuthTokenORM.token_kind
                            == LocalOAuthTokenKind.REFRESH.value,
                            McpOAuthTokenORM.revoked_at.is_(None),
                            McpOAuthTokenORM.expires_at > now,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.expires_at += extension_seconds
            return len(rows)


def _client_connection_record(
    client_row: McpOAuthClientORM,
    token_rows: tuple[McpOAuthTokenORM, ...],
    now: int,
) -> LocalOAuthClientConnectionRecord:
    """Execute client connection record.

    Args:
        client_row: Client row used by this operation.
        token_rows: Token rows used by this operation.
        now: Now used by this operation.

    Returns:
        LocalOAuthClientConnectionRecord result produced by client connection record.
    """
    refresh_rows = tuple(
        row for row in token_rows if row.token_kind == LocalOAuthTokenKind.REFRESH.value
    )
    unrevoked_refresh_rows = tuple(
        row for row in refresh_rows if row.revoked_at is None
    )
    active_refresh_rows = tuple(
        row for row in unrevoked_refresh_rows if row.expires_at > now
    )
    active_access_rows = tuple(
        row
        for row in token_rows
        if row.token_kind == LocalOAuthTokenKind.ACCESS.value
        and row.revoked_at is None
        and row.expires_at > now
    )
    reference_row = _latest_token_row(
        active_refresh_rows or unrevoked_refresh_rows or refresh_rows
    )
    active_family_count = len({row.family_id for row in active_refresh_rows})
    return LocalOAuthClientConnectionRecord(
        client_id=client_row.client_id,
        client_name=_metadata_text(client_row.client_metadata, "client_name"),
        issued_at=client_row.issued_at,
        status=_connection_status(
            refresh_rows=refresh_rows,
            unrevoked_refresh_rows=unrevoked_refresh_rows,
            active_refresh_rows=active_refresh_rows,
        ),
        connected=bool(active_refresh_rows),
        scopes=_connection_scopes(client_row.client_metadata, reference_row),
        resource=None if reference_row is None else reference_row.resource,
        access_token_expires_at=_max_expires_at(active_access_rows),
        refresh_token_expires_at=_max_expires_at(active_refresh_rows),
        active_token_families=active_family_count,
    )


def _connection_status(
    refresh_rows: tuple[McpOAuthTokenORM, ...],
    unrevoked_refresh_rows: tuple[McpOAuthTokenORM, ...],
    active_refresh_rows: tuple[McpOAuthTokenORM, ...],
) -> LocalOAuthClientConnectionStatus:
    """Execute connection status.

    Args:
        refresh_rows: Refresh rows used by this operation.
        unrevoked_refresh_rows: Unrevoked refresh rows used by this operation.
        active_refresh_rows: Active refresh rows used by this operation.

    Returns:
        LocalOAuthClientConnectionStatus result produced by connection status.
    """
    if active_refresh_rows:
        return LocalOAuthClientConnectionStatus.CONNECTED
    if unrevoked_refresh_rows:
        return LocalOAuthClientConnectionStatus.EXPIRED
    return LocalOAuthClientConnectionStatus.REGISTERED


def _connection_scopes(
    metadata: JSONObject,
    token_row: McpOAuthTokenORM | None,
) -> tuple[str, ...]:
    """Execute connection scopes.

    Args:
        metadata: Metadata used by this operation.
        token_row: Token row used by this operation.

    Returns:
        tuple[str, ...] result produced by connection scopes.
    """
    if token_row is not None:
        return tuple(token_row.scopes)
    scope = _metadata_text(metadata, "scope")
    if scope is None:
        return ()
    return tuple(item for item in scope.split() if item)


def _latest_token_row(
    token_rows: tuple[McpOAuthTokenORM, ...],
) -> McpOAuthTokenORM | None:
    """Execute latest token row.

    Args:
        token_rows: Token rows used by this operation.

    Returns:
        McpOAuthTokenORM | None result produced by latest token row.
    """
    if not token_rows:
        return None
    return max(token_rows, key=lambda row: row.created_at)


def _max_expires_at(token_rows: tuple[McpOAuthTokenORM, ...]) -> int | None:
    """Execute max expires at.

    Args:
        token_rows: Token rows used by this operation.

    Returns:
        int | None result produced by max expires at.
    """
    if not token_rows:
        return None
    return max(row.expires_at for row in token_rows)


def _metadata_text(metadata: JSONObject, key: str) -> str | None:
    """Execute metadata text.

    Args:
        metadata: Metadata used by this operation.
        key: Key used by this operation.

    Returns:
        str | None result produced by metadata text.
    """
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _add_token_pair(
    session: AsyncSession,
    client_id: str,
    scopes: list[str],
    resource: str,
    family_id: str,
    access_token_hash: str,
    refresh_token_hash: str,
    access_expires_at: int,
    refresh_expires_at: int,
    now: int,
) -> None:
    """Execute add token pair.

    Args:
        session: Active session used by this operation.
        client_id: Identifier for client.
        scopes: Scopes used by this operation.
        resource: Resource used by this operation.
        family_id: Identifier for family.
        access_token_hash: Access token hash used by this operation.
        refresh_token_hash: Refresh token hash used by this operation.
        access_expires_at: Access expires at used by this operation.
        refresh_expires_at: Refresh expires at used by this operation.
        now: Now used by this operation.
    """
    session.add_all(
        (
            McpOAuthTokenORM(
                token_hash=access_token_hash,
                token_kind=LocalOAuthTokenKind.ACCESS.value,
                family_id=family_id,
                client_id=client_id,
                scopes=list(scopes),
                resource=resource,
                expires_at=access_expires_at,
                revoked_at=None,
                created_at=now,
            ),
            McpOAuthTokenORM(
                token_hash=refresh_token_hash,
                token_kind=LocalOAuthTokenKind.REFRESH.value,
                family_id=family_id,
                client_id=client_id,
                scopes=list(scopes),
                resource=resource,
                expires_at=refresh_expires_at,
                revoked_at=None,
                created_at=now,
            ),
        )
    )
