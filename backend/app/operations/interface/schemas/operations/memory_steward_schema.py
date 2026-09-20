"""Memory Steward diagnose and seal response contracts."""

from __future__ import annotations

from typing import Annotated

from app.operations.application.steward.memory_steward_service import (
    StewardDiagnoseResult,
    StewardDiagnostic,
)
from app.operations.domain.event_enum.memory_steward_enums import MemoryStewardStatus
from app.operations.interface.schemas.operations.operational_readiness_detail_schema import (
    OperationalReadinessSnapshotResponse,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)


class MemoryStewardDiagnosticResponse(StrictSchemaModel):
    """One actionable steward diagnostic with detail and repair references."""

    code: Annotated[
        str,
        described_field("Code for this steward diagnostic response."),
    ]
    blocking: Annotated[
        bool,
        described_field("Blocking for this steward diagnostic response."),
    ]
    count: Annotated[
        int,
        described_field("Count for this steward diagnostic response."),
    ]
    detail_operation: Annotated[
        str,
        described_field("Detail operation for this steward diagnostic response."),
    ]
    recommended_operation: Annotated[
        str,
        described_field("Recommended operation for this steward diagnostic response."),
    ]

    @classmethod
    def from_entity(cls, entity: StewardDiagnostic) -> MemoryStewardDiagnosticResponse:
        """Map the internal diagnostic to the HTTP contract.

        Args:
            entity: Internal steward diagnostic.

        Returns:
            HTTP steward diagnostic response.
        """
        return cls(
            code=entity.code,
            blocking=entity.blocking,
            count=entity.count,
            detail_operation=entity.detail_operation,
            recommended_operation=entity.recommended_operation,
        )


class MemoryStewardDiagnoseResponse(StrictSchemaModel):
    """Composed steward verdict with diagnostics and the readiness evidence."""

    overall_status: Annotated[
        MemoryStewardStatus,
        described_field("Overall status for this steward diagnose response."),
    ]
    diagnostics: Annotated[
        list[MemoryStewardDiagnosticResponse],
        described_field("Diagnostics for this steward diagnose response."),
    ] = schema_list_default()
    readiness: Annotated[
        OperationalReadinessSnapshotResponse,
        described_field("Readiness evidence for this steward diagnose response."),
    ]

    @classmethod
    def from_entity(
        cls,
        result: StewardDiagnoseResult,
    ) -> MemoryStewardDiagnoseResponse:
        """Map the internal steward result to the HTTP contract.

        Args:
            result: Internal steward diagnose or seal result.

        Returns:
            HTTP steward diagnose response.
        """
        return cls(
            overall_status=result.overall_status,
            diagnostics=[
                MemoryStewardDiagnosticResponse.from_entity(diagnostic)
                for diagnostic in result.diagnostics
            ],
            readiness=OperationalReadinessSnapshotResponse.from_entity(
                result.readiness
            ),
        )
