"""Routes for Obsidian librarian execution operations."""

from typing import Annotated

from app.container import ApplicationContainer
from app.obsidian.application.librarian.workflow.obsidian_librarian_job_service import (
    ObsidianLibrarianJobService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.interface.schemas.obsidian.librarian.obsidian_librarian_job_schema import (
    ObsidianLibrarianJobResponse,
)
from app.obsidian.interface.schemas.obsidian.librarian.obsidian_librarian_review_schema import (
    ObsidianLibrarianReviewApplyRequestSchema,
    ObsidianLibrarianReviewQueueItemResponse,
    ObsidianLibrarianReviewQueueRequestSchema,
    ObsidianLibrarianReviewQueueResponse,
)
from app.obsidian.interface.schemas.obsidian.maintenance.obsidian_vault_inventory_schema import (
    ObsidianVaultInventoryItemResponse,
    ObsidianVaultInventoryRequestSchema,
    ObsidianVaultInventoryResponse,
)
from app.obsidian.interface.schemas.obsidian.maintenance.obsidian_vault_move_schema import (
    ObsidianVaultMoveApplyRequestSchema,
    ObsidianVaultMovePlanRequestSchema,
    ObsidianVaultMovePlanResponse,
    ObsidianVaultMoveReportResponse,
    ObsidianVaultPathSearchRequest,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import model_validate_json_body
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Depends, status

router = APIRouter(
    prefix="/obsidian",
    tags=["obsidian"],
)


@router.post(
    "/librarian/vault/inventory",
    response_model=ObsidianVaultInventoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Inventory managed Obsidian vault notes",
    description="List managed Markdown notes under a scope for librarian workflows.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def inventory_obsidian_vault_notes(
    request: ObsidianVaultInventoryRequestSchema,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianVaultInventoryResponse:
    """Inventory managed notes for typed librarian execution planning.

    Args:
        request: Inventory scope request.
        service: Obsidian application service.

    Returns:
        Managed note inventory response.
    """
    items = await service.inventory_vault(request.to_command())
    responses = [ObsidianVaultInventoryItemResponse.from_entity(item) for item in items]
    return ObsidianVaultInventoryResponse(items=responses, total=len(responses))


@router.post(
    "/librarian/review-queue",
    response_model=ObsidianLibrarianReviewQueueResponse,
    status_code=status.HTTP_200_OK,
    summary="List notes needing librarian curation",
    description=(
        "Return inbox, draft, legacy, and loose managed notes that should be "
        "classified, promoted, archived, or moved by a librarian workflow."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def list_obsidian_librarian_review_queue(
    request: ObsidianLibrarianReviewQueueRequestSchema,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianLibrarianReviewQueueResponse:
    """List notes that need librarian curation.

    Args:
        request: Queue scope request.
        service: Obsidian application service.

    Returns:
        Prioritized librarian review queue.
    """
    items = await service.librarian_review_queue(request.to_command())
    responses = [
        ObsidianLibrarianReviewQueueItemResponse.from_entity(item) for item in items
    ]
    return ObsidianLibrarianReviewQueueResponse(items=responses, total=len(responses))


@router.post(
    "/librarian/review-queue/move-plan",
    response_model=ObsidianVaultMovePlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Plan safe moves from librarian review queue",
    description=(
        "Convert current review-queue candidates into a dry-run safe move plan. "
        "This endpoint does not mutate the vault."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def plan_obsidian_librarian_review_moves(
    request: ObsidianLibrarianReviewQueueRequestSchema,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianVaultMovePlanResponse:
    """Plan safe note moves from the librarian review queue.

    Args:
        request: Queue scope request.
        service: Obsidian application service.

    Returns:
        Dry-run move plan for queue candidates.
    """
    plan = await service.plan_librarian_review_moves(request.to_command())
    return ObsidianVaultMovePlanResponse.from_entity(plan)


@router.post(
    "/librarian/review-queue/apply-moves",
    response_model=ObsidianVaultMoveReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply safe moves from librarian review queue",
    description=(
        "Convert current review-queue candidates into safe note moves, apply "
        "them through the existing no-hard-delete move workflow, reindex, and "
        "write report files."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def apply_obsidian_librarian_review_moves(
    request: ObsidianLibrarianReviewApplyRequestSchema,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianVaultMoveReportResponse:
    """Apply safe note moves generated from the librarian review queue.

    Args:
        request: Queue scope and report options.
        service: Obsidian application service.

    Returns:
        Safe move application report.
    """
    report = await service.apply_librarian_review_moves(request.to_command())
    return ObsidianVaultMoveReportResponse.from_entity(report)


@router.post(
    "/librarian/vault/path-search",
    response_model=ObsidianVaultInventoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Search managed Obsidian vault paths",
    description="Search managed note paths and metadata without relying on FTS.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def search_obsidian_vault_paths(
    request: Annotated[
        ObsidianVaultPathSearchRequest,
        Depends(model_validate_json_body(ObsidianVaultPathSearchRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianVaultInventoryResponse:
    """Search inventory metadata for typed librarian execution planning.

    Args:
        request: Path/metadata search request.
        service: Obsidian application service.

    Returns:
        Matching inventory items.
    """
    items = await service.search_vault_paths(
        query=request.query,
        scope_path=request.scope_path,
    )
    responses = [ObsidianVaultInventoryItemResponse.from_entity(item) for item in items]
    return ObsidianVaultInventoryResponse(items=responses, total=len(responses))


@router.post(
    "/librarian/vault/move-plan",
    response_model=ObsidianVaultMovePlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Plan safe Obsidian vault moves",
    description="Dry-run note moves with no hard delete and no overwrite.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def plan_obsidian_vault_moves(
    request: ObsidianVaultMovePlanRequestSchema,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianVaultMovePlanResponse:
    """Plan safe moves for a typed librarian vault workflow.

    Args:
        request: Requested safe move plan.
        service: Obsidian application service.

    Returns:
        Dry-run move plan.
    """
    plan = await service.plan_vault_moves(request.to_command())
    return ObsidianVaultMovePlanResponse.from_entity(plan)


@router.post(
    "/librarian/vault/apply-moves",
    response_model=ObsidianVaultMoveReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply safe Obsidian vault moves",
    description="Apply planned note moves, reindex, verify, and write reports.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def apply_obsidian_vault_moves(
    request: ObsidianVaultMoveApplyRequestSchema,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianVaultMoveReportResponse:
    """Apply safe note moves for a typed librarian vault workflow.

    Args:
        request: Safe move application request.
        service: Obsidian application service.

    Returns:
        Move application report.
    """
    report = await service.apply_vault_moves(request.to_command())
    return ObsidianVaultMoveReportResponse.from_entity(report)


@router.post(
    "/librarian/jobs",
    response_model=ObsidianLibrarianJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start in-process Obsidian librarian execution job",
    description=(
        "Start a best-effort in-process vault organization job and return job_id; "
        "job status is not restart-durable, but report files are written to the vault."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def start_obsidian_librarian_job(
    request: ObsidianVaultMoveApplyRequestSchema,
    background_tasks: BackgroundTasks,
    job_service: Annotated[
        ObsidianLibrarianJobService,
        Depends(Provide[ApplicationContainer.obsidian.job_service]),
    ],
) -> ObsidianLibrarianJobResponse:
    """Start a best-effort in-process librarian vault execution job.

    Args:
        request: Safe move application request.
        background_tasks: FastAPI background task collector.
        job_service: Librarian job service.

    Returns:
        Pending job status response.
    """
    job = job_service.create_vault_move_job()
    background_tasks.add_task(
        job_service.run_vault_move_job,
        job_id=job.job_id,
        request=request.to_command(),
    )
    return ObsidianLibrarianJobResponse.from_entity(job)


@router.get(
    "/librarian/jobs/{job_id}",
    response_model=ObsidianLibrarianJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Read Obsidian librarian job status",
    description=(
        "Return status and report handles for an in-process librarian execution job; "
        "unknown ids after restart return not found."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_obsidian_librarian_job(
    job_id: str,
    job_service: Annotated[
        ObsidianLibrarianJobService,
        Depends(Provide[ApplicationContainer.obsidian.job_service]),
    ],
) -> ObsidianLibrarianJobResponse:
    """Read one best-effort in-process librarian execution job status.

    Args:
        job_id: Librarian job id.
        job_service: Librarian job service.

    Returns:
        Current job status response.
    """
    return ObsidianLibrarianJobResponse.from_entity(job_service.get_job(job_id))


@router.get(
    "/librarian/jobs/{job_id}/report",
    response_model=ObsidianVaultMoveReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Read Obsidian librarian job report",
    description="Return the typed report for a completed librarian execution job.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_obsidian_librarian_job_report(
    job_id: str,
    job_service: Annotated[
        ObsidianLibrarianJobService,
        Depends(Provide[ApplicationContainer.obsidian.job_service]),
    ],
) -> ObsidianVaultMoveReportResponse:
    """Read one completed librarian execution job report.

    Args:
        job_id: Librarian job id.
        job_service: Librarian job service.

    Returns:
        Completed job move report.
    """
    report = job_service.get_report(job_id)
    return ObsidianVaultMoveReportResponse.from_entity(report)
