"""Skill-acquisition provider selection policy tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import anyio
from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import (
    AuthType,
    ProviderSecretKey,
    ProviderType,
)
from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.librarian.application.skill_acquisition.skill_acquisition_provider_selector import (
    SkillAcquisitionProviderSelector,
)


class _ProviderRepository:
    def __init__(self, providers: list[LibrarianProvider]) -> None:
        self._providers = providers

    async def list_all(self) -> list[LibrarianProvider]:
        return list(self._providers)

    async def get(self, provider_id: str) -> LibrarianProvider | None:
        return next((p for p in self._providers if p.id == provider_id), None)


class _SecretRepository:
    def __init__(self, values: dict[tuple[str, str], str]) -> None:
        self._values = values

    async def resolve(self, provider_id: str, key_name: str) -> str | None:
        return self._values.get((provider_id, key_name))


def _provider(
    provider_id: str,
    provider_type: ProviderType,
    auth_type: AuthType,
) -> LibrarianProvider:
    timestamp = datetime(2026, 8, 8, tzinfo=UTC)
    return LibrarianProvider(
        id=provider_id,
        name=provider_id,
        provider_type=provider_type,
        auth_type=auth_type,
        enabled=True,
        config={},
        created_at=timestamp,
        updated_at=timestamp,
    )


def _selector(
    providers: list[LibrarianProvider],
    secrets: dict[tuple[str, str], str],
) -> SkillAcquisitionProviderSelector:
    return SkillAcquisitionProviderSelector(
        provider_repository=cast(
            ILibrarianProviderRepository, _ProviderRepository(providers)
        ),
        credential_repository=cast(
            IProviderSecretRepository, _SecretRepository(secrets)
        ),
        now_provider=lambda: datetime(2026, 8, 8, tzinfo=UTC),
    )


def test_skill_acquisition_prefers_web_capable_openai_provider() -> None:
    """Automatic acquisition should prefer standard OpenAI when web research is available."""
    codex = _provider("codex", ProviderType.OPENAI_CODEX, AuthType.OAUTH)
    openai = _provider("openai", ProviderType.OPENAI, AuthType.API_KEY)
    selector = _selector(
        [codex, openai],
        {
            ("codex", ProviderSecretKey.OAUTH_REFRESH_TOKEN.value): "refresh",
            ("openai", ProviderSecretKey.API_KEY.value): "api-key",
        },
    )

    selected = anyio.run(selector.select, None)

    assert selected is not None
    assert selected.id == "openai"


def test_skill_acquisition_falls_back_to_other_executable_provider() -> None:
    """Automatic acquisition should still run when only Codex OAuth is executable."""
    codex = _provider("codex", ProviderType.OPENAI_CODEX, AuthType.OAUTH)
    selector = _selector(
        [codex],
        {("codex", ProviderSecretKey.OAUTH_REFRESH_TOKEN.value): "refresh"},
    )

    selected = anyio.run(selector.select, None)

    assert selected is not None
    assert selected.id == "codex"
