"""Provider execution readiness policy tests."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio
from app.librarian.application.delegation.provider_execution_policy import (
    provider_can_execute,
)
from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import (
    AuthType,
    ProviderSecretKey,
    ProviderType,
)
from app.connections.domain.repositories.librarian_repository import (
    IProviderSecretRepository,
)

FIXED_NOW = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
PROVIDER_ID = "00000000-0000-4000-8000-000000000701"


class ProviderExecutionSecretRepository(IProviderSecretRepository):
    """In-memory secret repository for execution policy tests."""

    def __init__(self, secrets: dict[str, str]) -> None:
        """Store provider secrets by key name."""
        self.secrets = secrets

    async def resolve(self, provider_id: str, key_name: str) -> str | None:
        """Return a stored secret when the provider id matches."""
        if provider_id != PROVIDER_ID:
            return None
        return self.secrets.get(key_name)

    async def set_secret(self, *, provider_id: str, key_name: str, value: str) -> None:
        """Set secret is unused by execution policy tests."""
        raise NotImplementedError

    async def delete_for_provider(self, provider_id: str, key_name: str) -> None:
        """Delete secret is unused by execution policy tests."""
        raise NotImplementedError


def _provider(*, enabled: bool = True) -> LibrarianProvider:
    """Return an OAuth provider row."""
    return LibrarianProvider(
        id=PROVIDER_ID,
        name="codex-oauth",
        provider_type=ProviderType.OPENAI_CODEX.value,
        auth_type=AuthType.OAUTH.value,
        enabled=enabled,
        config={},
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


def test_provider_can_execute_when_oauth_refresh_token_can_mint_access_token() -> None:
    """OAuth providers should be executable when a refresh token is available."""

    async def scenario() -> None:
        executable = await provider_can_execute(
            _provider(),
            ProviderExecutionSecretRepository(
                {ProviderSecretKey.OAUTH_REFRESH_TOKEN.value: "refresh-token"}
            ),
            lambda: FIXED_NOW,
        )
        assert executable is True

    anyio.run(scenario)


def test_provider_cannot_execute_when_oauth_access_token_is_expired_without_refresh() -> (
    None
):
    """OAuth providers should not execute with only an expired access token."""

    async def scenario() -> None:
        executable = await provider_can_execute(
            _provider(),
            ProviderExecutionSecretRepository(
                {
                    ProviderSecretKey.OAUTH_ACCESS_TOKEN.value: "access-token",
                    ProviderSecretKey.OAUTH_EXPIRES_AT.value: "2026-05-15T11:59:00+00:00",
                }
            ),
            lambda: FIXED_NOW,
        )
        assert executable is False

    anyio.run(scenario)
