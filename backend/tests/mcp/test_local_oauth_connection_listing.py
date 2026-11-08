"""PostgreSQL contracts for the public local OAuth connection listing."""

from __future__ import annotations

import asyncio
import os
from dataclasses import astuple

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.mcp_server.local_oauth.local_oauth_enums import (
    LocalOAuthClientConnectionStatus,
    LocalOAuthTokenKind,
)
from app.mcp_server.local_oauth.orm import McpOAuthClientORM, McpOAuthTokenORM
from app.mcp_server.local_oauth.repository import LocalMcpOAuthRepository

_NOW = 1_000_000


def _token_row(
    client_id: str,
    token_kind: LocalOAuthTokenKind,
    family_id: str,
    scopes: tuple[str, ...],
    resource: str,
    expires_at: int,
    created_at: int,
    revoked_at: int | None = None,
) -> McpOAuthTokenORM:
    return McpOAuthTokenORM(
        token_hash=f"{client_id}-{family_id}-{token_kind.value}-{created_at}",
        token_kind=token_kind.value,
        family_id=family_id,
        client_id=client_id,
        scopes=list(scopes),
        resource=resource,
        expires_at=expires_at,
        revoked_at=revoked_at,
        created_at=created_at,
    )


def test_list_client_connections_groups_postgresql_tokens_per_client() -> None:
    """List each registered client from only its tokens and public metadata."""

    async def scenario() -> None:
        engine = create_async_engine(os.environ["DATABASE_URL"])
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as session, session.begin():
                clients = (
                    (
                        "metadata-only",
                        {
                            "client_name": "Metadata only",
                            "scope": "metadata:read metadata:write",
                        },
                        10,
                    ),
                    (
                        "access-only",
                        {
                            "client_name": "Access only",
                            "scope": "fallback:scope",
                        },
                        20,
                    ),
                    ("revoked-only", {"client_name": "Revoked only"}, 30),
                    ("expired-refresh", {"client_name": "Expired refresh"}, 40),
                    (
                        "active-client",
                        {
                            "client_name": "Active client",
                            "scope": "metadata:must-not-win",
                        },
                        50,
                    ),
                    ("isolated-client", {"client_name": "Isolated client"}, 60),
                )
                session.add_all(
                    McpOAuthClientORM(
                        client_id=client_id,
                        client_secret_ciphertext=None,
                        client_metadata=metadata,
                        issued_at=issued_at,
                        secret_expires_at=None,
                    )
                    for client_id, metadata, issued_at in clients
                )
                session.add_all(
                    (
                        _token_row(
                            client_id="access-only",
                            token_kind=LocalOAuthTokenKind.ACCESS,
                            family_id="access-family",
                            scopes=("access:scope",),
                            resource="https://access-only.example/mcp",
                            expires_at=_NOW + 300,
                            created_at=100,
                        ),
                        _token_row(
                            client_id="revoked-only",
                            token_kind=LocalOAuthTokenKind.REFRESH,
                            family_id="revoked-family",
                            scopes=("revoked:scope",),
                            resource="https://revoked.example/mcp",
                            expires_at=_NOW + 500,
                            created_at=110,
                            revoked_at=_NOW - 1,
                        ),
                        _token_row(
                            client_id="expired-refresh",
                            token_kind=LocalOAuthTokenKind.REFRESH,
                            family_id="expired-family",
                            scopes=("expired:scope",),
                            resource="https://expired.example/mcp",
                            expires_at=_NOW - 1,
                            created_at=120,
                        ),
                        _token_row(
                            client_id="active-client",
                            token_kind=LocalOAuthTokenKind.REFRESH,
                            family_id="active-family-old",
                            scopes=("old:scope",),
                            resource="https://old.example/mcp",
                            expires_at=_NOW + 400,
                            created_at=130,
                        ),
                        _token_row(
                            client_id="active-client",
                            token_kind=LocalOAuthTokenKind.REFRESH,
                            family_id="active-family-current",
                            scopes=("current:read", "offline_access"),
                            resource="https://current.example/mcp",
                            expires_at=_NOW + 700,
                            created_at=140,
                        ),
                        _token_row(
                            client_id="active-client",
                            token_kind=LocalOAuthTokenKind.REFRESH,
                            family_id="expired-distraction-family",
                            scopes=("expired:distraction",),
                            resource="https://expired-distraction.example/mcp",
                            expires_at=_NOW,
                            created_at=150,
                        ),
                        _token_row(
                            client_id="active-client",
                            token_kind=LocalOAuthTokenKind.REFRESH,
                            family_id="revoked-distraction-family",
                            scopes=("revoked:distraction",),
                            resource="https://revoked-distraction.example/mcp",
                            expires_at=_NOW + 9_000,
                            created_at=160,
                            revoked_at=_NOW - 1,
                        ),
                        _token_row(
                            client_id="active-client",
                            token_kind=LocalOAuthTokenKind.ACCESS,
                            family_id="active-family-old",
                            scopes=("access:old",),
                            resource="https://access-old.example/mcp",
                            expires_at=_NOW + 800,
                            created_at=170,
                        ),
                        _token_row(
                            client_id="active-client",
                            token_kind=LocalOAuthTokenKind.ACCESS,
                            family_id="active-family-current",
                            scopes=("access:current",),
                            resource="https://access-current.example/mcp",
                            expires_at=_NOW + 900,
                            created_at=180,
                        ),
                        _token_row(
                            client_id="active-client",
                            token_kind=LocalOAuthTokenKind.ACCESS,
                            family_id="revoked-access-family",
                            scopes=("access:revoked",),
                            resource="https://access-revoked.example/mcp",
                            expires_at=_NOW + 9_000,
                            created_at=190,
                            revoked_at=_NOW - 1,
                        ),
                        _token_row(
                            client_id="active-client",
                            token_kind=LocalOAuthTokenKind.ACCESS,
                            family_id="expired-access-family",
                            scopes=("access:expired",),
                            resource="https://access-expired.example/mcp",
                            expires_at=_NOW,
                            created_at=200,
                        ),
                        _token_row(
                            client_id="isolated-client",
                            token_kind=LocalOAuthTokenKind.REFRESH,
                            family_id="isolated-family",
                            scopes=("isolated:scope",),
                            resource="https://isolated.example/mcp",
                            expires_at=_NOW + 600,
                            created_at=210,
                        ),
                    )
                )

            records = await LocalMcpOAuthRepository(sessions).list_client_connections(
                now=_NOW
            )
            records_by_client = {
                record.client_id: astuple(record) for record in records
            }
            assert len(records_by_client) == 6
            assert records_by_client == {
                "metadata-only": (
                    "metadata-only",
                    "Metadata only",
                    10,
                    LocalOAuthClientConnectionStatus.REGISTERED,
                    False,
                    ("metadata:read", "metadata:write"),
                    None,
                    None,
                    None,
                    0,
                ),
                "access-only": (
                    "access-only",
                    "Access only",
                    20,
                    LocalOAuthClientConnectionStatus.REGISTERED,
                    False,
                    ("fallback:scope",),
                    None,
                    _NOW + 300,
                    None,
                    0,
                ),
                "revoked-only": (
                    "revoked-only",
                    "Revoked only",
                    30,
                    LocalOAuthClientConnectionStatus.REGISTERED,
                    False,
                    ("revoked:scope",),
                    "https://revoked.example/mcp",
                    None,
                    None,
                    0,
                ),
                "expired-refresh": (
                    "expired-refresh",
                    "Expired refresh",
                    40,
                    LocalOAuthClientConnectionStatus.EXPIRED,
                    False,
                    ("expired:scope",),
                    "https://expired.example/mcp",
                    None,
                    None,
                    0,
                ),
                "active-client": (
                    "active-client",
                    "Active client",
                    50,
                    LocalOAuthClientConnectionStatus.CONNECTED,
                    True,
                    ("current:read", "offline_access"),
                    "https://current.example/mcp",
                    _NOW + 900,
                    _NOW + 700,
                    2,
                ),
                "isolated-client": (
                    "isolated-client",
                    "Isolated client",
                    60,
                    LocalOAuthClientConnectionStatus.CONNECTED,
                    True,
                    ("isolated:scope",),
                    "https://isolated.example/mcp",
                    None,
                    _NOW + 600,
                    1,
                ),
            }
        finally:
            await engine.dispose()

    asyncio.run(scenario())
