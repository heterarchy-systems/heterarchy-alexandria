"""Routes for operational readiness diagnostics."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.reconciliation.runtime.memory_reconciliation_readiness_service import (
    MemoryReconciliationReadinessService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.operations.application.readiness.operational_capability_policy import (
    capability_snapshot,
)
from app.operations.application.readiness.operational_readiness_cache import (
    OperationalReadinessCache,
)
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.interface.schemas.operations.operational_capability_schema import (
    OperationalCapabilitySnapshotResponse,
)
from app.operations.interface.schemas.operations.operational_readiness_detail_schema import (
    OperationalReadinessSnapshotResponse,
)
from app.shared.infrastructure.database import Database

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get(
    "/readiness",
    response_model=OperationalReadinessSnapshotResponse,
    status_code=status.HTTP_200_OK,
    summary="Get operational readiness",
    description=(
        "Return read-only database, vault, and RAG readiness plus a separate "
        "non-blocking canonical data-integrity status."
    ),
)
@inject
async def operational_readiness(
    database: Annotated[Database, Depends(Provide[ApplicationContainer.database])],
    context_service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
    obsidian_service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
    readiness_cache: Annotated[
        OperationalReadinessCache,
        Depends(Provide[ApplicationContainer.operational_readiness_cache]),
    ],
    reconciliation_service: Annotated[
        MemoryReconciliationReadinessService | None,
        Depends(
            Provide[ApplicationContainer.memory.memory_reconciliation_readiness_service]
        ),
    ],
) -> OperationalReadinessSnapshotResponse:
    """Return operational readiness snapshot.

    Args:
        database: Shared database coordinator.
        context_service: Context/RAG service.
        obsidian_service: Obsidian vault service.
        reconciliation_service: Memory reconciliation diagnostics service.

    Returns:
        Read-only operational readiness response.
    """
    service = OperationalReadinessService(
        database=database,
        context_service=context_service,
        obsidian_service=obsidian_service,
        reconciliation_service=reconciliation_service,
        readiness_cache=readiness_cache,
    )
    snapshot = await service.snapshot()
    return OperationalReadinessSnapshotResponse.from_entity(snapshot)


@router.get(
    "/capabilities",
    response_model=OperationalCapabilitySnapshotResponse,
    status_code=status.HTTP_200_OK,
    summary="Get independently assessed platform capabilities",
    description=(
        "Assess durable core memory independently from semantic retrieval and "
        "the optional external Librarian connection."
    ),
)
@inject
async def operational_capabilities(
    database: Annotated[Database, Depends(Provide[ApplicationContainer.database])],
    context_service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
    obsidian_service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
    readiness_cache: Annotated[
        OperationalReadinessCache,
        Depends(Provide[ApplicationContainer.operational_readiness_cache]),
    ],
    reconciliation_service: Annotated[
        MemoryReconciliationReadinessService | None,
        Depends(
            Provide[ApplicationContainer.memory.memory_reconciliation_readiness_service]
        ),
    ],
) -> OperationalCapabilitySnapshotResponse:
    """Return independently classified core, semantic, and Librarian states.

    Args:
        database: Shared database coordinator.
        context_service: Context and RAG health boundary.
        obsidian_service: Canonical Vault health boundary.
        reconciliation_service: Optional reconciliation diagnostics boundary.

    Returns:
        Independent capability readiness response.
    """
    service = OperationalReadinessService(
        database=database,
        context_service=context_service,
        obsidian_service=obsidian_service,
        reconciliation_service=reconciliation_service,
        readiness_cache=readiness_cache,
    )
    readiness = await service.snapshot()
    return OperationalCapabilitySnapshotResponse.from_entity(
        capability_snapshot(readiness)
    )
