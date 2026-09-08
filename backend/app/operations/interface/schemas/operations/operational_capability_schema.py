"""HTTP schemas for independently assessed platform capabilities."""

from __future__ import annotations

from typing import Annotated

from app.operations.domain.entities.operational_capability import (
    OperationalCapability,
    OperationalCapabilitySnapshot,
)
from app.operations.domain.event_enum.operational_capability_enums import (
    OperationalCapabilityFreshness,
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
    source_revision: Annotated[
        str | None,
        described_field("Indexed source revision for this capability response."),
    ] = None
    projection_revision: Annotated[
        str | None,
        described_field("Projection revision for this capability response."),
    ] = None
    freshness: Annotated[
        OperationalCapabilityFreshness,
        described_field("Freshness evidence for this capability response."),
    ] = OperationalCapabilityFreshness.UNKNOWN

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
            source_revision=item.source_revision,
            projection_revision=item.projection_revision,
            freshness=item.freshness,
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
    source: Annotated[
        OperationalCapabilityResponse,
        described_field("Canonical source capability evidence."),
    ]
    metadata_index: Annotated[
        OperationalCapabilityResponse,
        described_field("Metadata index capability evidence."),
    ]
    fts: Annotated[
        OperationalCapabilityResponse,
        described_field("FTS capability evidence."),
    ]
    vector: Annotated[
        OperationalCapabilityResponse,
        described_field("Vector capability evidence."),
    ]
    embedding: Annotated[
        OperationalCapabilityResponse,
        described_field("Embedding capability evidence."),
    ]
    graph: Annotated[
        OperationalCapabilityResponse,
        described_field("Graph capability evidence."),
    ]
    reconciliation: Annotated[
        OperationalCapabilityResponse,
        described_field("Reconciliation capability evidence."),
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
            source=OperationalCapabilityResponse.from_entity(snapshot.source),
            metadata_index=OperationalCapabilityResponse.from_entity(
                snapshot.metadata_index
            ),
            fts=OperationalCapabilityResponse.from_entity(snapshot.fts),
            vector=OperationalCapabilityResponse.from_entity(snapshot.vector),
            embedding=OperationalCapabilityResponse.from_entity(snapshot.embedding),
            graph=OperationalCapabilityResponse.from_entity(snapshot.graph),
            reconciliation=OperationalCapabilityResponse.from_entity(
                snapshot.reconciliation
            ),
        )
