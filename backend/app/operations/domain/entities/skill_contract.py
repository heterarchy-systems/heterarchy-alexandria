"""Skill and runtime contract status read models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class SkillContractStatus:
    """One skill bundle's compatibility with the live runtime contract."""

    name: str
    path: str
    content_hash: str
    status: str
    declared_tools: tuple[str, ...] = ()
    missing_tools: tuple[str, ...] = ()
    retired_terms: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    drift_reasons: tuple[str, ...] = ()
    vault_mirror_path: str | None = None
    vault_mirror_hash: str | None = None
    verified_at: str | None = None
    mirror_status: str = "UNVERIFIED"


@dataclass(frozen=True, slots=True)
class SkillRuntimeContract:
    """Loaded runtime capability evidence for publication decisions."""

    tool_names: tuple[str, ...]
    capability_fingerprint: str
    runtime_revision: str | None
    source_repo_revision: str | None
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class SkillContractReport:
    """Read-only skill and runtime contract compatibility report."""

    compatible: bool
    repo_revision: str | None
    bundle_hash: str
    checked_at: datetime
    skills: tuple[SkillContractStatus, ...] = ()
    runtime_tool_names: tuple[str, ...] = ()
    drift_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    capability_fingerprint: str | None = None
    runtime_schema_version: int = 1


def skill_bundle_hash(skills: tuple[SkillContractStatus, ...]) -> str:
    """Hash the ordered skill bundle contents for vault-mirror drift checks.

    Args:
        skills: Per-skill statuses in report order.

    Returns:
        Deterministic bundle hash over skill names and content hashes.
    """
    digest = sha256()
    for skill in skills:
        digest.update(skill.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(skill.content_hash.encode("utf-8"))
    return digest.hexdigest()
