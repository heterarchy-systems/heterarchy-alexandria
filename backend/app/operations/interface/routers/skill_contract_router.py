"""Skill and runtime contract status route."""

from typing import Annotated

import anyio
import anyio.to_thread
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status

from app.container import ApplicationContainer
from app.operations.application.skill_contract.skill_contract_status_service import (
    SkillContractStatusService,
)
from app.operations.interface.schemas.operations.skill_contract_schema import (
    SkillContractReportResponse,
)
from app.platform.middleware.database_session import (
    mark_database_transaction_read_only,
)

router = APIRouter(prefix="/skills", tags=["operations-skills"])


@router.get(
    "/contract-status",
    response_model=SkillContractReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Skill and runtime contract status",
    description=(
        "Compare repo skill bundles with the live registered MCP toolset and "
        "report compatibility, drift reasons, and bundle hashes."
    ),
)
@inject
async def skill_contract_status(
    http_request: Request,
    service: Annotated[
        SkillContractStatusService,
        Depends(Provide[ApplicationContainer.skill_contract_status_service]),
    ],
) -> SkillContractReportResponse:
    """Return the read-only skill and runtime compatibility report."""
    mark_database_transaction_read_only(http_request)
    report = await anyio.to_thread.run_sync(service.status)
    return SkillContractReportResponse.from_entity(report)
