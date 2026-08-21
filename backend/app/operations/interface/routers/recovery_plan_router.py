"""Routes for recovery dry-run planning."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.reconciliation.runtime.memory_reconciliation_readiness_service import (
    MemoryReconciliationReadinessService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.operations.application.recovery.planning.recovery_plan_service import (
    RecoveryPlanService,
)
from app.operations.interface.schemas.operations.recovery_plan_schema import (
    RecoveryPlanRequestSchema,
    RecoveryPlanResponse,
)
from app.shared.infrastructure.database import Database

router = APIRouter(prefix="/operations/recovery", tags=["operations"])


@router.post(
    "/plan",
    response_model=RecoveryPlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Plan operational recovery",
    description="Return a read-only recovery dry-run plan without mutating files.",
)
@inject
async def recovery_plan(
    request: RecoveryPlanRequestSchema,
    database: Annotated[Database, Depends(Provide[ApplicationContainer.database])],
    context_service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
    obsidian_service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
    reconciliation_service: Annotated[
        MemoryReconciliationReadinessService | None,
        Depends(
            Provide[ApplicationContainer.memory.memory_reconciliation_readiness_service]
        ),
    ],
) -> RecoveryPlanResponse:
    """Return recovery dry-run plan.

    Args:
        request: Recovery plan request payload.
        database: Shared database coordinator.
        context_service: Context/RAG service.
        obsidian_service: Obsidian vault service.
        reconciliation_service: Memory reconciliation diagnostics service.

    Returns:
        Recovery dry-run plan response.
    """
    service = RecoveryPlanService(
        database=database,
        context_service=context_service,
        obsidian_service=obsidian_service,
        reconciliation_service=reconciliation_service,
    )
    plan = await service.plan(request.to_contract())
    return RecoveryPlanResponse.from_entity(plan)
