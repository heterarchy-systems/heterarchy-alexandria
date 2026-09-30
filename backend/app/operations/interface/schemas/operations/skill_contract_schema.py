"""Public skill compatibility report with JSON-safe serialization."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from app.operations.domain.entities.skill_contract import SkillContractReport
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class SkillContractStatusResponse(StrictSchemaModel):
    """One skill's tool and architecture compatibility evidence."""

    name: Annotated[str, described_field("Skill name.")]
    path: Annotated[str, described_field("Repository skill source path.")]
    content_hash: Annotated[str, described_field("Exact skill source hash.")]
    status: Annotated[str, described_field("Runtime compatibility state.")]
    declared_tools: Annotated[tuple[str, ...], described_field("Declared tools.")]
    missing_tools: Annotated[tuple[str, ...], described_field("Absent runtime tools.")]
    retired_terms: Annotated[
        tuple[str, ...], described_field("Retired authority claims.")
    ]
    warnings: Annotated[tuple[str, ...], described_field("Distribution warnings.")]
    drift_reasons: Annotated[
        tuple[str, ...], described_field("Exact compatibility or mirror drift causes.")
    ] = ()
    vault_mirror_path: Annotated[
        str | None, described_field("Canonical Active mirror path when resolved.")
    ] = None
    vault_mirror_hash: Annotated[
        str | None,
        described_field("Exact submitted source hash recorded in the mirror."),
    ] = None
    verified_at: Annotated[
        str | None, described_field("Last recorded runtime verification timestamp.")
    ] = None
    mirror_status: Annotated[
        str, described_field("MATCHED, DRIFT, MISSING or UNVERIFIED mirror evidence.")
    ] = "UNVERIFIED"


class SkillContractReportResponse(StrictSchemaModel):
    """Read-only report over repository skill and registered runtime contracts."""

    compatible: Annotated[bool, described_field("All checked contracts compatible.")]
    repo_revision: Annotated[str | None, described_field("Reported runtime revision.")]
    bundle_hash: Annotated[str, described_field("Combined skill source hash.")]
    checked_at: Annotated[datetime, described_field("Compatibility check timestamp.")]
    skills: Annotated[
        tuple[SkillContractStatusResponse, ...], described_field("Checked skills.")
    ]
    runtime_tool_names: Annotated[
        tuple[str, ...], described_field("Registered tool names.")
    ]
    drift_reasons: Annotated[
        tuple[str, ...], described_field("Compatibility failures.")
    ]
    warnings: Annotated[tuple[str, ...], described_field("Distribution warnings.")]
    capability_fingerprint: Annotated[
        str | None, described_field("Loaded input and output manifest fingerprint.")
    ] = None
    runtime_schema_version: Annotated[
        int, described_field("Current declared runtime contract revision.")
    ] = 1

    @classmethod
    def from_entity(cls, report: SkillContractReport) -> SkillContractReportResponse:
        """Serialize the typed application report at the public boundary.

        Args:
            report: Current compatibility evidence.

        Returns:
            Validated response with nested skill contracts.
        """
        return cls.model_validate(report, from_attributes=True)
