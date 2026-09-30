"""Read-only skill and runtime contract compatibility checks.

Skill documentation drifts silently while the runtime contract evolves. This
service parses the repo skill bundles, extracts their declared MCP tools and
architecture claims, and compares them with the live registered toolset so an
agent can see which skill body is current and compatible without manually
comparing the vault, repo, and runtime surfaces.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_json,
    parse_markdown_document,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.operations.application.skill_contract.skill_publication_policy import (
    skill_body_hash,
)
from app.operations.domain.entities.skill_contract import (
    SkillContractReport,
    SkillContractStatus,
    SkillRuntimeContract,
    skill_bundle_hash,
)
from app.operations.domain.skill_contract_policy import evaluate_skill_contract
from app.platform.config.app_config import AppConfig
from app.shared.types.extra_types import JSONObject

_SKILL_FILE_NAME: Final[str] = "SKILL.md"


@dataclass(frozen=True, slots=True)
class _ActiveSkillMirror:
    """Exact bounded source and attestation for one Active publication."""

    path: str
    body: str
    metadata: JSONObject
    ambiguous: bool = False


def _frontmatter_name(text: str, fallback: str) -> str:
    """Read the skill frontmatter name, falling back to the bundle name."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            return stripped.split(":", maxsplit=1)[1].strip() or fallback
        if stripped and not stripped.startswith("---"):
            break
    return fallback


class SkillContractStatusService:
    """Compare repo skill bundles with the live registered MCP toolset."""

    def __init__(
        self,
        config: AppConfig,
        tool_names_provider: Callable[[], tuple[str, ...]],
        runtime_contract_provider: Callable[[], SkillRuntimeContract] | None = None,
        vault_config_store: ObsidianVaultConfigStore | None = None,
        catalog_exposed: bool | None = None,
    ) -> None:
        """Initialize the read-only contract boundary.

        Args:
            config: App config carrying the runtime revision and the optional
                skill bundle root override.
            tool_names_provider: Live registered MCP tool names.
            runtime_contract_provider: Loaded input/output schema manifest.
            vault_config_store: Active Vault mirror location owner.
            catalog_exposed: Observed external catalog distribution, if known.
        """
        self._config = config
        self._tool_names_provider = tool_names_provider
        self._runtime_contract_provider = runtime_contract_provider
        self._vault_config_store = vault_config_store
        self._catalog_exposed = catalog_exposed

    def status(self) -> SkillContractReport:
        """Build one skill and runtime compatibility report.

        Returns:
            Read-only compatibility report over every discovered skill.
        """
        warnings: list[str] = []
        if self._catalog_exposed is False:
            warnings.append("skill_catalog_not_exposed")
        runtime = (
            self._runtime_contract_provider()
            if self._runtime_contract_provider is not None
            else SkillRuntimeContract(
                self._tool_names_provider(),
                "",
                self._config.runtime_revision,
                self._config.runtime_revision,
            )
        )
        mirrors = self._mirrors(warnings)
        skill_root = self._skill_root()
        skills: list[SkillContractStatus] = []
        matched_mirrors: set[str] = set()
        if skill_root is None or not skill_root.is_dir():
            warnings.append("skill_bundle_root_unavailable")
        else:
            for skill_dir in sorted(
                path for path in skill_root.iterdir() if path.is_dir()
            ):
                skill_file = skill_dir / _SKILL_FILE_NAME
                if not skill_file.is_file():
                    continue
                skill = self._skill_status(skill_dir, skill_file, runtime)
                mirror_key = "skills_alexandria/" + skill_dir.name + "/SKILL.md"
                mirror = mirrors.get(mirror_key)
                if self._vault_config_store is not None:
                    if mirror is None:
                        skill = replace(
                            skill,
                            mirror_status="MISSING",
                            warnings=("vault_mirror_missing",),
                        )
                    else:
                        matched_mirrors.add(mirror_key)
                        skill = self._compare_mirror(
                            skill,
                            mirror,
                            runtime,
                            repo_hash=skill_body_hash(
                                skill_file.read_text(encoding="utf-8")
                            ),
                        )
                skills.append(skill)
        for mirror_key, mirror in sorted(mirrors.items()):
            if mirror_key in matched_mirrors:
                continue
            skill = evaluate_skill_contract(
                mirror.body,
                mirror.metadata,
                runtime,
                name=Path(mirror.path).stem,
                path=mirror.path,
            )
            skills.append(self._compare_mirror(skill, mirror, runtime, repo_hash=None))
        drift_reasons = [
            reason for skill in skills for reason in self._drift_reasons(skill)
        ]
        return SkillContractReport(
            compatible=not drift_reasons
            and "skill_bundle_root_unavailable" not in warnings,
            repo_revision=self._config.runtime_revision,
            bundle_hash=skill_bundle_hash(tuple(skills)),
            checked_at=datetime.now(UTC),
            skills=tuple(skills),
            runtime_tool_names=tuple(sorted(self._tool_names_provider())),
            drift_reasons=tuple(drift_reasons),
            warnings=tuple(warnings),
            capability_fingerprint=runtime.capability_fingerprint or None,
            runtime_schema_version=runtime.schema_version,
        )

    def _skill_status(
        self,
        skill_dir: Path,
        skill_file: Path,
        runtime: SkillRuntimeContract,
    ) -> SkillContractStatus:
        """Check one skill bundle against the live toolset."""
        raw = skill_file.read_text(encoding="utf-8")
        document = parse_markdown_document(raw)
        return evaluate_skill_contract(
            raw,
            frontmatter_json(document.frontmatter),
            runtime,
            name=_frontmatter_name(raw, skill_dir.name),
            path=skill_file.as_posix(),
        )

    def _drift_reasons(self, skill: SkillContractStatus) -> list[str]:
        """Build bounded drift reasons for one skill."""
        return [f"{skill.name}: {reason}" for reason in skill.drift_reasons]

    def _compare_mirror(
        self,
        skill: SkillContractStatus,
        mirror: _ActiveSkillMirror,
        runtime: SkillRuntimeContract,
        *,
        repo_hash: str | None,
    ) -> SkillContractStatus:
        """Compare source, loaded schema and build attestations independently."""
        reasons = list(skill.drift_reasons)
        source_hash = mirror.metadata.get("skill_source_hash")
        verified_at = mirror.metadata.get("verified_at")
        if repo_hash is None:
            reasons.append("active mirror repo identity unavailable")
        elif source_hash != repo_hash:
            reasons.append("vault mirror differs from repo")
        if mirror.ambiguous:
            reasons.append("ambiguous Active mirrors for repo identity")
        if mirror.metadata.get("skill_published_body_hash") != skill_body_hash(
            mirror.body
        ):
            reasons.append("vault mirror differs from body attestation")
        expected = {
            "verified_runtime_revision": runtime.runtime_revision,
            "source_repo_revision": runtime.source_repo_revision,
            "verified_schema_version": runtime.schema_version,
            "capability_fingerprint": runtime.capability_fingerprint,
        }
        for field, current in expected.items():
            if not current or mirror.metadata.get(field) != current:
                reasons.append("vault mirror stale or unverified " + field)
        try:
            verified = datetime.fromisoformat(
                verified_at if isinstance(verified_at, str) else ""
            )
            if verified.utcoffset() is None:
                raise ValueError("verification timestamp must be aware")
        except ValueError:
            reasons.append("vault mirror verified_at unavailable or invalid")
        verdict = evaluate_skill_contract(
            mirror.body, mirror.metadata, runtime, name=skill.name, path=mirror.path
        )
        reasons.extend(verdict.drift_reasons)
        return replace(
            skill,
            status="DRIFT"
            if reasons and skill.status == "COMPATIBLE"
            else skill.status,
            mirror_status="DRIFT" if reasons else "MATCHED",
            vault_mirror_path=mirror.path,
            vault_mirror_hash=source_hash if isinstance(source_hash, str) else None,
            verified_at=verified_at if isinstance(verified_at, str) else None,
            drift_reasons=tuple(dict.fromkeys(reasons)),
        )

    def _mirrors(self, warnings: list[str]) -> dict[str, _ActiveSkillMirror]:
        """Read bounded Active mirrors through the canonical source boundary."""
        if self._vault_config_store is None:
            return {}
        config = self._vault_config_store.current()
        root = config.vault_path / config.alexandria_root / "Skills" / "Active"
        result: dict[str, _ActiveSkillMirror] = {}
        if not root.is_dir():
            warnings.append("active_skill_mirrors_unavailable")
            return result
        paths = sorted(root.rglob("*.md"))
        if len(paths) > 64:
            warnings.append("skill_mirror_inventory_bounded_at_64")
        for path in paths[:64]:
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(
                    root.resolve()
                ):
                    raise ValueError("mirror path is outside canonical root")
                with path.open("rb") as source:
                    raw = source.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError("mirror exceeds byte bound")
                document = parse_markdown_document(raw.decode("utf-8"))
                metadata = frontmatter_json(document.frontmatter)
            except (OSError, UnicodeError, ValueError):
                warnings.append("skill_mirror_source_unavailable:" + path.name)
                continue
            if metadata.get("alexandria_type") != "skill" or metadata.get(
                "status", "active"
            ) not in {"active", "current"}:
                continue
            repo_path = metadata.get("repo_path")
            if not isinstance(repo_path, str) or not repo_path:
                warnings.append("skill_mirror_repo_identity_missing:" + path.name)
                repo_path = "vault:" + str(path.relative_to(config.vault_path))
            mirror = _ActiveSkillMirror(
                path=str(path.relative_to(config.vault_path)),
                body=document.body,
                metadata=metadata,
            )
            if repo_path in result:
                warnings.append("ambiguous_active_skill_mirror:" + repo_path)
                result[repo_path] = replace(result[repo_path], ambiguous=True)
            else:
                result[repo_path] = mirror
        return result

    def _skill_root(self) -> Path | None:
        """Resolve the configured or repository-local skill bundle root."""
        override = self._config.skill_bundle_root
        if override:
            return Path(override)
        default = Path(__file__).resolve().parents[5] / "skills_alexandria"
        return default if default.is_dir() else None
