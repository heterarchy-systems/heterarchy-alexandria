"""Skill and runtime contract compatibility tests."""

from __future__ import annotations

from pathlib import Path

from tests.config_test_data import app_config_values

from app.operations.application.skill_contract.skill_contract_status_service import (
    SkillContractStatusService,
)
from app.platform.config.app_config import AppConfig

_MATCHING_SKILL = """---
name: matching-skill
description: Uses only registered tools.
---

Use `alexandria_recall` and `alexandria_verify`.
"""

_RETIRED_SKILL = """---
name: retired-skill
description: References a retired traversal authority.
---

Traversal authority stays in Neo4j.
"""

_HISTORICAL_SKILL = """---
name: historical-skill
description: Mentions retired systems only as history.
---

<!-- historical -->
The old librarian graph ran on Neo4j.
<!-- /historical -->

The librarian handoff was [historical].
Today `alexandria_recall` is used instead.
"""

_MISSING_TOOL_SKILL = """---
name: missing-tool-skill
description: Declares a tool the runtime does not register.
---

Use `alexandria_time_travel`.
"""


def _service(
    skill_root: Path | None, tools: tuple[str, ...]
) -> tuple[SkillContractStatusService, AppConfig]:
    config = AppConfig(
        _env_file=None,
        **app_config_values(
            skill_bundle_root=None if skill_root is None else str(skill_root)
        ),
    )
    return SkillContractStatusService(config, lambda: tools), config


def _write_skill(root: Path, name: str, body: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


def test_matching_skill_reports_compatible(tmp_path: Path) -> None:
    """A skill whose declared tools are registered is compatible."""
    _write_skill(tmp_path, "matching", _MATCHING_SKILL)
    service, _config = _service(tmp_path, ("alexandria_recall", "alexandria_verify"))

    report = service.status()

    assert report.compatible is True
    assert report.drift_reasons == ()
    assert report.skills[0].status == "COMPATIBLE"
    assert report.skills[0].declared_tools == ("alexandria_recall", "alexandria_verify")
    assert report.bundle_hash


def test_retired_architecture_claim_is_incompatible(tmp_path: Path) -> None:
    """An unmarked retired architecture term blocks compatibility."""
    _write_skill(tmp_path, "retired", _RETIRED_SKILL)
    service, _config = _service(tmp_path, ("alexandria_recall",))

    report = service.status()

    assert report.compatible is False
    assert report.skills[0].status == "INCOMPATIBLE"
    assert report.skills[0].retired_terms == ("neo4j",)
    assert any("retired architecture claim: neo4j" in r for r in report.drift_reasons)


def test_missing_declared_tool_is_incompatible(tmp_path: Path) -> None:
    """A declared tool the runtime does not register blocks compatibility."""
    _write_skill(tmp_path, "missing", _MISSING_TOOL_SKILL)
    service, _config = _service(tmp_path, ("alexandria_recall",))

    report = service.status()

    assert report.compatible is False
    assert report.skills[0].missing_tools == ("alexandria_time_travel",)


def test_marked_historical_references_are_allowed(tmp_path: Path) -> None:
    """Historical regions and [historical] lines never count as live claims."""
    _write_skill(tmp_path, "historical", _HISTORICAL_SKILL)
    service, _config = _service(tmp_path, ("alexandria_recall",))

    report = service.status()

    assert report.compatible is True
    assert report.skills[0].retired_terms == ()
    assert report.skills[0].declared_tools == ("alexandria_recall",)


def test_bundle_hash_tracks_skill_content(tmp_path: Path) -> None:
    """Changing a skill body changes the bundle hash."""
    _write_skill(tmp_path, "matching", _MATCHING_SKILL)
    service, _config = _service(tmp_path, ("alexandria_recall",))
    first = service.status().bundle_hash

    _write_skill(tmp_path, "matching", _MATCHING_SKILL + "\nExtra guidance.\n")
    second = service.status().bundle_hash

    assert first != second


def test_missing_bundle_root_warns_without_crash(tmp_path: Path) -> None:
    """An unavailable skill root is an explicit warning, not a failure."""
    service, _config = _service(tmp_path / "does-not-exist", ())

    report = service.status()

    assert report.compatible is False
    assert report.warnings == ("skill_bundle_root_unavailable",)
    assert report.skills == ()


def test_repository_skill_bundles_match_runtime_toolset() -> None:
    """The shipped skill bundles must stay compatible with the live toolset."""
    from app.mcp_server.runtime_tool_catalog import registered_runtime_tool_names

    service, _config = _service(None, registered_runtime_tool_names())

    report = service.status()

    assert report.warnings == ()
    assert report.compatible is True, report.drift_reasons
    assert {skill.name for skill in report.skills} >= {
        "alexandria-library",
        "connection-hub",
        "operational-sync",
        "alexandria-safe-markdown-storage",
    }


def test_vault_mirror_drift_and_catalog_gap_are_independent_runtime_evidence(
    tmp_path: Path,
) -> None:
    """Repo/mirror hash drift is observable without claiming catalog loss corrupts runtime."""
    from app.obsidian.infrastructure.markdown.frontmatter import (
        render_markdown_document,
    )
    from app.obsidian.infrastructure.obsidian_vault_config_store import (
        ObsidianVaultConfigStore,
    )
    from app.operations.application.skill_contract.skill_publication_policy import (
        SkillPublicationPolicy,
        skill_body_hash,
    )
    from app.operations.domain.entities.skill_contract import SkillRuntimeContract

    repo = tmp_path / "skills"
    _write_skill(repo, "matching", _MATCHING_SKILL)
    vault = tmp_path / "vault"
    active = vault / "Alexandria" / "Skills" / "Active"
    active.mkdir(parents=True)
    runtime = SkillRuntimeContract(
        ("alexandria_recall", "alexandria_verify"),
        "a" * 64,
        "runtime-test",
        "source-test",
    )
    verification = SkillPublicationPolicy(lambda: runtime).validate(
        _MATCHING_SKILL, {}, path="Alexandria/Skills/Active/Matching.md"
    )
    metadata = {
        "id": "skill_matching",
        "alexandria_type": "skill",
        "status": "active",
        "repo_path": "skills_alexandria/matching/SKILL.md",
        **verification,
        "skill_source_hash": skill_body_hash(_MATCHING_SKILL),
    }
    (active / "Matching.md").write_text(
        render_markdown_document(metadata, _MATCHING_SKILL), encoding="utf-8"
    )
    config = AppConfig(_env_file=None, **app_config_values(skill_bundle_root=str(repo)))
    store = ObsidianVaultConfigStore(
        default_vault_path=str(vault),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    service = SkillContractStatusService(
        config,
        lambda: runtime.tool_names,
        runtime_contract_provider=lambda: runtime,
        vault_config_store=store,
        catalog_exposed=False,
    )
    matched = service.status()
    assert matched.compatible is True
    assert matched.skills[0].mirror_status == "MATCHED"
    assert "skill_catalog_not_exposed" in matched.warnings
    drifted_runtime = SkillRuntimeContract(
        runtime.tool_names, "b" * 64, "runtime-next", "source-next", 2
    )
    runtime_drift = SkillContractStatusService(
        config,
        lambda: drifted_runtime.tool_names,
        runtime_contract_provider=lambda: drifted_runtime,
        vault_config_store=store,
    ).status()
    assert runtime_drift.skills[0].mirror_status == "DRIFT"
    assert any("capability_fingerprint" in r for r in runtime_drift.drift_reasons)
    assert any("verified_runtime_revision" in r for r in runtime_drift.drift_reasons)
    _write_skill(repo, "matching", _MATCHING_SKILL + "\nNew semantic guidance.\n")
    changed = service.status()
    assert changed.skills[0].status == "DRIFT"
    assert changed.skills[0].vault_mirror_path == "Alexandria/Skills/Active/Matching.md"
    assert changed.skills[0].verified_at is not None
