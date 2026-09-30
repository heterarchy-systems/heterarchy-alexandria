"""Active Skill source effects require compatible, versioned runtime evidence."""

from pathlib import Path

import anyio
import pytest
from tests.obsidian.test_obsidian_frontmatter_repair import _services

from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.operations.application.skill_contract.skill_publication_policy import (
    SkillPublicationPolicy,
)
from app.operations.domain.entities.skill_contract import SkillRuntimeContract
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError


@pytest.mark.parametrize(
    ("body", "metadata"),
    [
        ("Use `alexandria_missing_tool`.", {}),
        ("Neo4j owns traversal.", {}),
        ("Run heterarchy-alexandria policy apply.", {}),
        ("Use `alexandria_recall`.", {"runtime_contract_min": 2}),
        ("Use `alexandria_recall`.", {"capability_fingerprint": "b" * 64}),
    ],
)
def test_incompatible_active_skill_does_not_mutate_source(
    tmp_path: Path, body: str, metadata: dict
) -> None:
    async def scenario():
        database, session, _ = await _services(tmp_path)
        runtime = SkillRuntimeContract(
            ("alexandria_recall",), "a" * 64, "test-runtime", "test-source"
        )
        service = ObsidianService(
            repository=SqlAlchemyObsidianIndexRepository(session),
            vault_path=str(tmp_path / "vault"),
            skill_publication_policy=SkillPublicationPolicy(lambda: runtime),
        )
        try:
            with pytest.raises(
                ObsidianValidationError, match="SKILL_RUNTIME_INCOMPATIBLE"
            ):
                await service.save_note(
                    ObsidianSaveNote(
                        title="Active",
                        body=body,
                        alexandria_type=AlexandriaNoteType.SKILL,
                        relative_path="Alexandria/Skills/Active/Active.md",
                        frontmatter=metadata,
                    )
                )
            assert not (
                tmp_path / "vault" / "Alexandria/Skills/Active/Active.md"
            ).exists()
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_matching_active_skill_records_exact_runtime_and_body_receipt(
    tmp_path: Path,
) -> None:
    async def scenario():
        database, session, _ = await _services(tmp_path)
        runtime = SkillRuntimeContract(
            ("alexandria_recall",), "a" * 64, "test-runtime", "test-source"
        )
        service = ObsidianService(
            repository=SqlAlchemyObsidianIndexRepository(session),
            vault_path=str(tmp_path / "vault"),
            skill_publication_policy=SkillPublicationPolicy(lambda: runtime),
        )
        try:
            note = await service.save_note(
                ObsidianSaveNote(
                    title="Active",
                    body="<!-- historical -->Neo4j was used.<!-- /historical -->\nUse `alexandria_recall`.",
                    alexandria_type=AlexandriaNoteType.SKILL,
                    relative_path="Alexandria/Skills/Active/Active.md",
                )
            )
            assert note.frontmatter["verified_runtime_revision"] == "test-runtime"
            assert note.frontmatter["source_repo_revision"] == "test-source"
            assert note.frontmatter["capability_fingerprint"] == "a" * 64
            assert note.frontmatter["verified_schema_version"] == 1
            assert note.frontmatter["skill_published_body_hash"]
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_draft_move_cannot_bypass_active_publication_gate(tmp_path: Path) -> None:
    from app.obsidian.domain.contracts.obsidian_contracts import (
        ObsidianVaultMoveApplyRequest,
        ObsidianVaultMoveRequest,
    )

    async def scenario():
        database, session, _ = await _services(tmp_path)
        runtime = SkillRuntimeContract(
            ("alexandria_recall",), "a" * 64, "test-runtime", "test-source"
        )
        service = ObsidianService(
            repository=SqlAlchemyObsidianIndexRepository(session),
            vault_path=str(tmp_path / "vault"),
            skill_publication_policy=SkillPublicationPolicy(lambda: runtime),
        )
        try:
            draft = await service.save_note(
                ObsidianSaveNote(
                    title="Retired",
                    body="Neo4j owns traversal.",
                    alexandria_type=AlexandriaNoteType.SKILL,
                )
            )
            original = (tmp_path / "vault" / draft.relative_path).read_bytes()
            with pytest.raises(
                ObsidianValidationError, match="SKILL_RUNTIME_INCOMPATIBLE"
            ):
                await service.apply_vault_moves(
                    ObsidianVaultMoveApplyRequest(
                        moves=(
                            ObsidianVaultMoveRequest(
                                source_path=draft.relative_path,
                                destination_path="Alexandria/Skills/Active/Retired.md",
                                reason="publish",
                            ),
                        ),
                        reindex=False,
                    )
                )
            assert (tmp_path / "vault" / draft.relative_path).read_bytes() == original
            assert not (
                tmp_path / "vault" / "Alexandria/Skills/Active/Retired.md"
            ).exists()
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)
