"""Canonical path and logical report identity resolver tests."""

from __future__ import annotations

import os

from pathlib import Path

import anyio
from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def test_canonical_identity_resolves_declared_report_alias_and_exact_path(
    tmp_path: Path,
) -> None:
    """Resolver should use canonical frontmatter aliases instead of hardcoded names."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            store = ObsidianVaultConfigStore(
                default_vault_path=str(tmp_path / "vault"),
                default_alexandria_root="Alexandria",
                config_path=None,
            )
            obsidian = ObsidianService(
                repository=repository,
                vault_config_store=store,
            )
            service = ObsidianCanonicalIdentityService(
                obsidian_service=obsidian,
                vault_config_store=store,
            )
            note = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Ripple Morning Read XRP 2026-08-03",
                    body="# Ripple Morning Read\n",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx-ripple-morning-read",
                    relative_path=(
                        "Alexandria/Contexts/Projects/Crypto Intelligence Trader/"
                        "Daily/2026/08/Ripple Morning Read/XRP/"
                        "Ripple Morning Read XRP 2026-08-03.md"
                    ),
                    project="Crypto Intelligence Trader",
                    frontmatter={
                        "scope": "PROJECT",
                        "report_family": "Ripple Morning Read",
                        "report_aliases": ["XRP Morning Read"],
                        "date": "2026-08-03",
                        "entity": "XRP",
                    },
                )
            )

            exact = await service.check_path(
                note.relative_path.removeprefix("Alexandria/")
            )
            resolved = await service.resolve(
                project="Crypto Intelligence Trader",
                report="XRP Morning Read",
                date="2026-08-03",
                entity="XRP",
            )
            generated = await service.resolve(
                project="Crypto Intelligence Trader",
                report="Ethereum Morning Read",
                date="2026-08-04",
                entity="Ethereum",
            )
        finally:
            await session.close()
            await database.shutdown()

        assert exact.exists is True
        assert exact.note_id == note.note_id
        assert exact.relative_path == note.relative_path
        assert resolved.resolution == "EXISTING_CANONICAL_FAMILY"
        assert resolved.canonical_report_family == "Ripple Morning Read"
        assert resolved.canonical_path == note.relative_path
        assert resolved.existing_note_id == note.note_id
        assert resolved.aliases == ("XRP Morning Read",)
        assert generated.resolution == "NEW_CANONICAL_IDENTITY"
        assert generated.canonical_path.startswith(
            "Alexandria/Contexts/Projects/Crypto Intelligence Trader/Daily/2026/08/"
        )

    anyio.run(scenario)


def test_canonical_identity_matches_frontmatter_not_inventory_search_fields(
    tmp_path: Path,
) -> None:
    """Exact identity matching must inspect canonical frontmatter on every note."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            store = ObsidianVaultConfigStore(
                default_vault_path=str(tmp_path / "vault"),
                default_alexandria_root="Alexandria",
                config_path=None,
            )
            obsidian = ObsidianService(
                repository=repository,
                vault_config_store=store,
            )
            existing = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Opaque Record",
                    body="# Opaque Record\n",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    relative_path="Alexandria/Contexts/opaque-record.md",
                    project="Crypto Intelligence Trader",
                    frontmatter={
                        "scope": "PROJECT",
                        "report_family": "Morning Read",
                        "date": "2026-08-03",
                        "entity": "Ethereum",
                        "edition": "asia",
                    },
                )
            )
            result = await ObsidianCanonicalIdentityService(
                obsidian_service=obsidian,
                vault_config_store=store,
            ).resolve(
                project="Crypto Intelligence Trader",
                report="Morning Read",
                date="2026-08-03",
                entity="Ethereum",
                edition="asia",
            )
        finally:
            await session.close()
            await database.shutdown()

        assert result.resolution == "EXISTING_CANONICAL_FAMILY"
        assert result.existing_note_id == existing.note_id
        assert result.canonical_path == existing.relative_path

    anyio.run(scenario)
