"""Shared Skill declaration policy; runtime registration and I/O remain adapters."""

import re
from hashlib import sha256

from app.operations.domain.entities.skill_contract import (
    SkillContractStatus,
    SkillRuntimeContract,
)
from app.shared.types.extra_types import JSONObject

_TOOLS = re.compile(r"\b(alexandria_[a-z_]+)(?=[`(])")
_HISTORY = re.compile(
    r"<!--\s*historical\s*-->.*?<!--\s*/historical\s*-->", re.IGNORECASE | re.DOTALL
)
_REMOVED_CLI = re.compile(r"\bheterarchy-alexandria\s+(?:policy|doctor|vault)\b")


def evaluate_skill_contract(
    body: str,
    metadata: JSONObject,
    runtime: SkillRuntimeContract,
    *,
    name: str,
    path: str,
) -> SkillContractStatus:
    """Check executable declarations without inventing missing capabilities.

    Args:
        body: Exact Skill text proposed for publication.
        metadata: Declared version bounds and optional pinned manifest.
        runtime: Loaded registered capability evidence.
        name: Skill identity for diagnostics.
        path: Exact source or intended managed path.

    Returns:
        Compatibility verdict with concrete drift reasons.
    """
    claims = "\n".join(
        line
        for line in _HISTORY.sub("", body).splitlines()
        if "[historical]" not in line.casefold()
    )
    declared = set(_TOOLS.findall(claims)) - {"alexandria_type", "alexandria_root"}
    reasons: list[str] = []
    required = metadata.get("required_tools", [])
    if isinstance(required, list) and all(isinstance(tool, str) for tool in required):
        declared.update(tool for tool in required if isinstance(tool, str))
    else:
        reasons.append("required_tools must be a string list")
    missing = tuple(sorted(declared - set(runtime.tool_names)))
    retired = tuple(
        term
        for term in ("neo4j", "librarian")
        if re.search(rf"\b{term}\b", claims, re.IGNORECASE)
    )
    reasons.extend(f"declared tool not registered: {tool}" for tool in missing)
    reasons.extend(f"retired architecture claim: {term}" for term in retired)
    if _REMOVED_CLI.search(claims):
        reasons.append("removed CLI command")
    minimum, maximum = (
        metadata.get("runtime_contract_min", 1),
        metadata.get("runtime_contract_max", 1),
    )
    if (
        not isinstance(minimum, int)
        or isinstance(minimum, bool)
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or not minimum <= runtime.schema_version <= maximum
    ):
        reasons.append("runtime contract version outside declared bounds")
    contract_version = metadata.get("skill_contract_version", 1)
    if contract_version != 1 or isinstance(contract_version, bool):
        reasons.append("unsupported skill contract version")
    pinned = metadata.get("capability_fingerprint")
    if pinned is not None and pinned != runtime.capability_fingerprint:
        reasons.append("capability fingerprint mismatch")
    return SkillContractStatus(
        name=name,
        path=path,
        content_hash=sha256(body.encode()).hexdigest(),
        status="INCOMPATIBLE" if reasons else "COMPATIBLE",
        declared_tools=tuple(sorted(declared)),
        missing_tools=missing,
        retired_terms=retired,
        drift_reasons=tuple(reasons),
    )
