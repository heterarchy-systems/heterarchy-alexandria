"""Routes for operational readiness diagnostics."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.operations.application.readiness.operational_capability_policy import (
    capability_snapshot,
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
    service: Annotated[
        OperationalReadinessService,
        Depends(Provide[ApplicationContainer.operational_readiness_service]),
    ],
) -> OperationalReadinessSnapshotResponse:
    """Return the current operational readiness snapshot.

    Args:
        service: Request-scoped operational readiness application service.

    Returns:
        Read-only operational readiness response.
    """
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
    service: Annotated[
        OperationalReadinessService,
        Depends(Provide[ApplicationContainer.operational_readiness_service]),
    ],
) -> OperationalCapabilitySnapshotResponse:
    """Return independently classified core, semantic, and Librarian states.

    Args:
        service: Request-scoped operational readiness application service.

    Returns:
        Independent capability readiness response.
    """
    readiness = await service.snapshot()
    return OperationalCapabilitySnapshotResponse.from_entity(
        capability_snapshot(readiness)
    )
