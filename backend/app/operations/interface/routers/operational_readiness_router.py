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
from app.operations.application.steward.memory_steward_service import (
    MemoryStewardDiagnoseService,
    MemoryStewardSealService,
)
from app.operations.interface.schemas.operations.memory_steward_schema import (
    MemoryStewardDiagnoseResponse,
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
        "Assess durable core memory independently from optional semantic retrieval."
    ),
)
@inject
async def operational_capabilities(
    service: Annotated[
        OperationalReadinessService,
        Depends(Provide[ApplicationContainer.operational_readiness_service]),
    ],
) -> OperationalCapabilitySnapshotResponse:
    """Return independently classified core and semantic states.

    Args:
        service: Request-scoped operational readiness application service.

    Returns:
        Independent capability readiness response.
    """
    readiness = await service.snapshot()
    return OperationalCapabilitySnapshotResponse.from_entity(
        capability_snapshot(readiness)
    )


@router.get(
    "/memory-steward/diagnose",
    response_model=MemoryStewardDiagnoseResponse,
    status_code=status.HTTP_200_OK,
    summary="Compose Memory Steward diagnostics",
    description=(
        "Compose the authoritative readiness snapshot into actionable Memory "
        "Steward diagnostics with detail and repair operation references."
    ),
)
@inject
async def memory_steward_diagnose(
    service: Annotated[
        MemoryStewardDiagnoseService,
        Depends(Provide[ApplicationContainer.memory_steward_diagnose_service]),
    ],
) -> MemoryStewardDiagnoseResponse:
    """Return composed Memory Steward diagnostics.

    Args:
        service: Request-scoped Memory Steward diagnose application service.

    Returns:
        Composed steward diagnose response.
    """
    result = await service.diagnose()
    return MemoryStewardDiagnoseResponse.from_entity(result)


@router.get(
    "/memory-steward/seal",
    response_model=MemoryStewardDiagnoseResponse,
    status_code=status.HTTP_200_OK,
    summary="Run the Memory Steward seal verification",
    description=(
        "Verify the final state of one memory circulation and report residual "
        "diagnostics as READY, READY_WITH_RESIDUALS, NOT_READY, or FAILED."
    ),
)
@inject
async def memory_steward_seal(
    service: Annotated[
        MemoryStewardSealService,
        Depends(Provide[ApplicationContainer.memory_steward_seal_service]),
    ],
) -> MemoryStewardDiagnoseResponse:
    """Return the seal verification verdict for the current state.

    Args:
        service: Request-scoped Memory Steward seal application service.

    Returns:
        Composed steward seal response.
    """
    result = await service.seal()
    return MemoryStewardDiagnoseResponse.from_entity(result)
