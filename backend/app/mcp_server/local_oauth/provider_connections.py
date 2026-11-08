"""Local operator operations for registered OAuth client connections."""

from __future__ import annotations

from app.mcp_server.local_oauth.contracts import (
    LocalMcpOAuthSettings,
    LocalOAuthClientConnectionRecord,
)
from app.mcp_server.local_oauth.provider_approval import current_epoch_seconds
from app.mcp_server.local_oauth.repository import LocalMcpOAuthRepository


class LocalMcpOAuthConnectionService:
    """Own public-safe connection listing, extension and deletion."""

    def __init__(
        self,
        repository: LocalMcpOAuthRepository,
        settings: LocalMcpOAuthSettings,
    ) -> None:
        """Create the local connection manager.

        Args:
            repository: Shared durable OAuth aggregate repository.
            settings: Local access and refresh token policy.
        """
        self._repository = repository
        self._settings = settings

    async def list_client_connections(
        self,
    ) -> tuple[LocalOAuthClientConnectionRecord, ...]:
        """List OAuth clients without exposing bearer tokens.

        Returns:
            Public-safe client connection records.
        """
        return await self._repository.list_client_connections(current_epoch_seconds())

    async def extend_client_connection(
        self,
        client_id: str,
    ) -> LocalOAuthClientConnectionRecord | None:
        """Extend an active refresh-token window.

        Args:
            client_id: Registered OAuth client id.

        Returns:
            Updated connection record, or None when it is inactive.
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

    async def delete_client_connection(self, client_id: str) -> bool:
        """Delete one client and all related credential state.

        Args:
            client_id: Registered OAuth client id.

        Returns:
            Whether the client aggregate existed and was deleted.
        """
        return await self._repository.delete_client(client_id)

    async def _client_connection(
        self,
        client_id: str,
    ) -> LocalOAuthClientConnectionRecord | None:
        """Read back one connection after its refresh-token extension.

        Args:
            client_id: Registered OAuth client id.

        Returns:
            Updated public-safe connection record, or None if it expired.
        """
        for connection in await self.list_client_connections():
            if connection.client_id == client_id:
                return connection
        return None
