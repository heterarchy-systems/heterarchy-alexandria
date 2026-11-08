"""Public skill compatibility report with JSON-safe serialization."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.operations.domain.entities.skill_contract import SkillContractReport
from app.shared.schemas.common_schemas import StrictSchemaModel


class SkillContractStatusResponse(StrictSchemaModel):
    """One skill's tool and architecture compatibility evidence."""

    name: Annotated[str, Field(description="Skill name.")]
    path: Annotated[str, Field(description="Repository skill source path.")]
    content_hash: Annotated[str, Field(description="Exact skill source hash.")]
    status: Annotated[str, Field(description="Runtime compatibility state.")]
    declared_tools: Annotated[tuple[str, ...], Field(description="Declared tools.")]
    missing_tools: Annotated[
        tuple[str, ...], Field(description="Absent runtime tools.")
    ]
    retired_terms: Annotated[
        tuple[str, ...], Field(description="Retired authority claims.")
    ]
    warnings: Annotated[tuple[str, ...], Field(description="Distribution warnings.")]
    drift_reasons: Annotated[
        tuple[str, ...],
        Field(description="Exact compatibility or mirror drift causes."),
    ] = ()
    vault_mirror_path: Annotated[
        str | None, Field(description="Canonical Active mirror path when resolved.")
    ] = None
    vault_mirror_hash: Annotated[
        str | None,
        Field(description="Exact submitted source hash recorded in the mirror."),
    ] = None
    verified_at: Annotated[
        str | None, Field(description="Last recorded runtime verification timestamp.")
    ] = None
    mirror_status: Annotated[
        str, Field(description="MATCHED, DRIFT, MISSING or UNVERIFIED mirror evidence.")
    ] = "UNVERIFIED"


class SkillContractReportResponse(StrictSchemaModel):
    """Read-only report over repository skill and registered runtime contracts."""

    compatible: Annotated[bool, Field(description="All checked contracts compatible.")]
    repo_revision: Annotated[
        str | None, Field(description="Reported runtime revision.")
    ]
    bundle_hash: Annotated[str, Field(description="Combined skill source hash.")]
    checked_at: Annotated[datetime, Field(description="Compatibility check timestamp.")]
    skills: Annotated[
        tuple[SkillContractStatusResponse, ...], Field(description="Checked skills.")
    ]
    runtime_tool_names: Annotated[
        tuple[str, ...], Field(description="Registered tool names.")
    ]
    drift_reasons: Annotated[
        tuple[str, ...], Field(description="Compatibility failures.")
    ]
    warnings: Annotated[tuple[str, ...], Field(description="Distribution warnings.")]
    capability_fingerprint: Annotated[
        str | None, Field(description="Loaded input and output manifest fingerprint.")
    ] = None
    runtime_schema_version: Annotated[
        int, Field(description="Current declared runtime contract revision.")
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
