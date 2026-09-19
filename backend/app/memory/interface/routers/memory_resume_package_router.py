"""Routes for versioned resume context packages."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.memory.application.memory_compacts.resume_package.resume_package_contracts import (
    ResumePackageView,
)
from app.memory.application.memory_compacts.resume_package.resume_package_service import (
    MemoryResumePackageService,
)
from app.memory.interface.schemas.memory_compact.memory_resume_package_schema import (
    MemoryResumePackageCreateRequest,
    MemoryResumePackageResponse,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import (
    MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter(prefix="/memory/resume-packages", tags=["memory-resume-packages"])


@router.post(
    "",
    response_model=MemoryResumePackageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create resume package",
    description=(
        "Seal a versioned worker-handoff resume package as a CURRENT Memory "
        "Compact: evidence is validated against stored Contexts, duplicate "
        "drafts are deduplicated, and a new revision supersedes the previous "
        "project CURRENT package. The package is data only."
    ),
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def create_memory_resume_package(
    request: Annotated[
        MemoryResumePackageCreateRequest,
        Depends(model_validate_json_body(MemoryResumePackageCreateRequest)),
    ],
    service: Annotated[
        MemoryResumePackageService,
        Depends(Provide[ApplicationContainer.memory.memory_resume_package_service]),
    ],
) -> MemoryResumePackageResponse:
    """Seal one versioned resume context package.

    Args:
        request: Public resume package creation payload.
        service: Resume package application service.

    Returns:
        Created or deduplicated resume package response.
    """
    seal = await service.create_resume_package(request.to_draft())
    view = await service.get_resume_package(seal.package_id)
    return MemoryResumePackageResponse.from_view(
        view,
        deduplicated=seal.deduplicated,
    )


@router.get(
    "/{package_id}",
    response_model=MemoryResumePackageResponse,
    status_code=status.HTTP_200_OK,
    summary="Get resume package",
    description=(
        "Reopen one sealed resume context package as a structured view with "
        "parsed sections, lineage, revision, evidence references, and "
        "deduplication state."
    ),
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_memory_resume_package(
    package_id: str,
    service: Annotated[
        MemoryResumePackageService,
        Depends(Provide[ApplicationContainer.memory.memory_resume_package_service]),
    ],
) -> MemoryResumePackageResponse:
    """Reopen one resume package as a structured view.

    Args:
        package_id: Memory Compact identifier of the resume package.
        service: Resume package application service.

    Returns:
        Structured resume package response.
    """
    view: ResumePackageView = await service.get_resume_package(package_id)
    return MemoryResumePackageResponse.from_view(
        view,
        deduplicated=view.deduplicated,
    )


__all__ = ("router",)
