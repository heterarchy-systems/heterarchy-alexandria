"""Durable skill-acquisition job command contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
    SkillAcquisitionJobStatus,
)
from app.librarian.domain.event_enum.skill_acquisition_enums import (
    ItemStatus,
    RiskLevel,
)
from app.librarian.domain.types.skill_acquisition_payload_types import (
    SkillSchemaPayload,
)
from app.shared.types.extra_types import JSONObject


def _empty_skill_schema() -> SkillSchemaPayload:
    """Execute empty skill schema.

    Returns:
        SkillSchemaPayload result produced by empty skill schema.
    """
    return {}


@dataclass(slots=True, kw_only=True)
class SkillAcquisitionJobCreate:
    """Fields required to create one durable skill-acquisition job."""

    id: str
    prompt: str
    agent_name: str
    project: str | None
    task_summary: str | None
    status: SkillAcquisitionJobStatus
    provider_id: str | None
    librarian_profile_id: str | None
    result_summary: str | None
    evidence_urls: tuple[str, ...] = field(default_factory=tuple)
    error_message: str | None = None
    skill_id: str | None = None
    context_id: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    stage: SkillAcquisitionJobStage | None = None
    progress_summary: str | None = None
    skill_note_path: str | None = None
    reindex_status: str | None = None
    verification_status: str | None = None
    handoff: JSONObject | None = None
    repair_hint: str | None = None
    search_snapshot: JSONObject | None = None
    acquisition_override_reason: str | None = None
    prompt_reference: str | None = None
    prompt_reference_hash: str | None = None

    def __post_init__(self) -> None:
        """Normalize job evidence URLs to an immutable sequence."""
        self.evidence_urls = tuple(self.evidence_urls)


@dataclass(slots=True, kw_only=True)
class SkillAcquisitionJobUpdate:
    """Fields allowed when updating one durable skill-acquisition job."""

    status: SkillAcquisitionJobStatus
    result_summary: str | None = None
    evidence_urls: tuple[str, ...] = field(default_factory=tuple)
    error_message: str | None = None
    skill_id: str | None = None
    context_id: str | None = None
    updated_at: datetime
    completed_at: datetime | None = None
    stage: SkillAcquisitionJobStage | None = None
    progress_summary: str | None = None
    skill_note_path: str | None = None
    reindex_status: str | None = None
    verification_status: str | None = None
    handoff: JSONObject | None = None
    repair_hint: str | None = None
    search_snapshot: JSONObject | None = None
    acquisition_override_reason: str | None = None
    prompt_reference: str | None = None
    prompt_reference_hash: str | None = None

    def __post_init__(self) -> None:
        """Normalize updated evidence URLs to an immutable sequence."""
        self.evidence_urls = tuple(self.evidence_urls)


@dataclass(slots=True, kw_only=True)
class SkillAcquisitionEvidenceItem:
    """Claim-linked source evidence for an acquired skill artifact."""

    url_or_path: str
    title: str | None = None
    source_kind: str | None = None
    publisher_or_repository: str | None = None
    accessed_at: str | None = None
    supports_claims: tuple[str, ...] = field(default_factory=tuple)
    freshness: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        """Normalize supported claims to an immutable sequence."""
        self.supports_claims = tuple(self.supports_claims)


@dataclass(slots=True, kw_only=True)
class SkillAcquisitionArtifact:
    """Structured skill artifact produced by librarian or agent acquisition."""

    title: str
    purpose: str
    content: str
    summary: str | None = None
    category_id: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    input_schema: SkillSchemaPayload = field(default_factory=_empty_skill_schema)
    output_schema: SkillSchemaPayload = field(default_factory=_empty_skill_schema)
    usage_example: str | None = None
    required_tools: tuple[str, ...] = field(default_factory=tuple)
    risk_level: RiskLevel = RiskLevel.LOW
    version: str = "1.0.0"
    created_by_name: str | None = None
    activate: bool = False
    status: ItemStatus = ItemStatus.DRAFT
    evidence_urls: tuple[str, ...] = field(default_factory=tuple)
    evidence_items: tuple[SkillAcquisitionEvidenceItem, ...] = field(
        default_factory=tuple
    )
    source_summary: str | None = None
    next_steps: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize artifact collections to immutable values."""
        self.tags = tuple(self.tags)
        self.required_tools = tuple(self.required_tools)
        self.evidence_urls = tuple(self.evidence_urls)
        self.evidence_items = tuple(self.evidence_items)
        self.next_steps = tuple(self.next_steps)
