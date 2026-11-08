"""HTTP schemas for independently assessed platform capabilities."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.operations.domain.entities.operational_capability import (
    OperationalCapability,
    OperationalCapabilitySnapshot,
)
from app.operations.domain.event_enum.operational_capability_enums import (
    OperationalCapabilityFreshness,
    OperationalCapabilityState,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default
from app.shared.schemas.datetime_schemas import AwareTimestamp


class OperationalCapabilityResponse(StrictSchemaModel):
    """One independently assessed platform capability."""

    state: Annotated[
        OperationalCapabilityState,
        Field(description="State for this operational capability response."),
    ]
    ready: Annotated[
        bool, Field(description="Ready for this operational capability response.")
    ]
    blockers: Annotated[
        list[str],
        Field(description="Blockers for this operational capability response."),
    ] = schema_list_default()
    warnings: Annotated[
        list[str],
        Field(description="Warnings for this operational capability response."),
    ] = schema_list_default()
    source_revision: Annotated[
        str | None,
        Field(description="Indexed source revision for this capability response."),
    ] = None
    projection_revision: Annotated[
        str | None,
        Field(description="Projection revision for this capability response."),
    ] = None
    freshness: Annotated[
        OperationalCapabilityFreshness,
        Field(description="Freshness evidence for this capability response."),
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
        Field(
            description="Checked at for this operational capability snapshot response."
        ),
    ]
    core_memory: Annotated[
        OperationalCapabilityResponse,
        Field(
            description="Core memory for this operational capability snapshot response."
        ),
    ]
    semantic_retrieval: Annotated[
        OperationalCapabilityResponse,
        Field(
            description="Semantic retrieval for this operational capability snapshot response."
        ),
    ]
    source: Annotated[
        OperationalCapabilityResponse,
        Field(description="Canonical source capability evidence."),
    ]
    metadata_index: Annotated[
        OperationalCapabilityResponse,
        Field(description="Metadata index capability evidence."),
    ]
    fts: Annotated[
        OperationalCapabilityResponse,
        Field(description="FTS capability evidence."),
    ]
    vector: Annotated[
        OperationalCapabilityResponse,
        Field(description="Vector capability evidence."),
    ]
    embedding: Annotated[
        OperationalCapabilityResponse,
        Field(description="Embedding capability evidence."),
    ]
    graph: Annotated[
        OperationalCapabilityResponse,
        Field(description="Graph capability evidence."),
    ]
    reconciliation: Annotated[
        OperationalCapabilityResponse,
        Field(description="Reconciliation capability evidence."),
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
