"""Project local OAuth persistence rows into public-safe client connection state."""

from __future__ import annotations

from app.mcp_server.local_oauth.contracts import (
    LocalOAuthClientConnectionRecord,
)
from app.mcp_server.local_oauth.local_oauth_enums import (
    LocalOAuthClientConnectionStatus,
    LocalOAuthTokenKind,
)
from app.mcp_server.local_oauth.orm import (
    McpOAuthClientORM,
    McpOAuthTokenORM,
)
from app.shared.types.extra_types import JSONObject


def client_connection_record(
    client_row: McpOAuthClientORM,
    token_rows: tuple[McpOAuthTokenORM, ...],
    now: int,
) -> LocalOAuthClientConnectionRecord:
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
    if active_refresh_rows:
        return LocalOAuthClientConnectionStatus.CONNECTED
    if unrevoked_refresh_rows:
        return LocalOAuthClientConnectionStatus.EXPIRED
    return LocalOAuthClientConnectionStatus.REGISTERED


def _connection_scopes(
    metadata: JSONObject,
    token_row: McpOAuthTokenORM | None,
) -> tuple[str, ...]:
    if token_row is not None:
        return tuple(token_row.scopes)
    scope = _metadata_text(metadata, "scope")
    if scope is None:
        return ()
    return tuple(item for item in scope.split() if item)


def _latest_token_row(
    token_rows: tuple[McpOAuthTokenORM, ...],
) -> McpOAuthTokenORM | None:
    if not token_rows:
        return None
    return max(token_rows, key=lambda row: row.created_at)


def _max_expires_at(token_rows: tuple[McpOAuthTokenORM, ...]) -> int | None:
    if not token_rows:
        return None
    return max(row.expires_at for row in token_rows)


def _metadata_text(metadata: JSONObject, key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None
