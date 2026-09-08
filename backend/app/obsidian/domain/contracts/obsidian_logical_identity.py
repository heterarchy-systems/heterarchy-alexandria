"""Logical report identity independent of physical note identifiers and paths."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianLogicalIdentity:
    """Existing canonical resolver coordinates for a recurring logical artifact."""

    project: str
    report: str
    date: str
    entity: str
    edition: str | None = None
