"""HTTP schemas for independently assessed platform capabilities."""

from __future__ import annotations

from typing import Annotated

from app.operations.domain.entities.operational_capability import (
    OperationalCapability,
    OperationalCapabilitySnapshot,
)
from app.operations.domain.event_enum.operational_capability_enums import (
    OperationalCapabilityState,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp


class OperationalCapabilityResponse(StrictSchemaModel):
    """One independently assessed platform capability."""

    state: Annotated[
        OperationalCapabilityState,
        described_field("State for this operational capability response."),
    ]
    ready: Annotated[
        bool, described_field("Ready for this operational capability response.")
    ]
    blockers: Annotated[
        list[str], described_field("Blockers for this operational capability response.")
    ] = schema_list_default()
    warnings: Annotated[
        list[str], described_field("Warnings for this operational capability response.")
    ] = schema_list_default()

    @classmethod
    def from_entity(
        cls,
        item: OperationalCapability,
    ) -> OperationalCapabilityResponse:
        """Build this schema from a domain entity."""
        return cls(
            state=item.state,
            ready=item.ready,
            blockers=list(item.blockers),
            warnings=list(item.warnings),
        )


class OperationalCapabilitySnapshotResponse(StrictSchemaModel):
    """Core and semantic readiness."""

    checked_at: Annotated[
        AwareTimestamp,
        described_field(
            "Checked at for this operational capability snapshot response."
        ),
    ]
    core_memory: Annotated[
        OperationalCapabilityResponse,
        described_field(
            "Core memory for this operational capability snapshot response."
        ),
    ]
    semantic_retrieval: Annotated[
        OperationalCapabilityResponse,
        described_field(
            "Semantic retrieval for this operational capability snapshot response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalCapabilitySnapshot,
    ) -> OperationalCapabilitySnapshotResponse:
        """Build this schema from a domain entity."""
        return cls(
            checked_at=snapshot.checked_at,
            core_memory=OperationalCapabilityResponse.from_entity(snapshot.core_memory),
            semantic_retrieval=OperationalCapabilityResponse.from_entity(
                snapshot.semantic_retrieval
            ),
        )
