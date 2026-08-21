"""Focused skill-library search and acquisition job routes."""

import logging
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Annotated, cast

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Depends, status

from app.container import ApplicationContainer
from app.librarian.application.skill_acquisition.skill_acquisition_runner import (
    SkillAcquisitionRunner,
)
from app.librarian.application.skill_acquisition.skill_acquisition_service import (
    SkillAcquisitionService,
)
from app.librarian.application.skill_artifacts.skill_artifact_publisher import (
    ObsidianSkillArtifactPublisher,
)
from app.librarian.application.skill_library.skill_library_search_service import (
    SkillLibrarySearchService,
)
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStatus,
)
from app.librarian.interface.schemas.librarian.skill_acquisition_schemas import (
    SkillAcquisitionJobRequest,
    SkillAcquisitionJobResponse,
    skill_acquisition_job_response,
)
from app.librarian.interface.schemas.librarian.skill_search_schemas import (
    SkillCapabilitySearchRequest,
    SkillCapabilitySearchResponse,
    skill_capability_search_response,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import LIBRARIAN_ROUTE_EXCEPTION_MAPPING
from app.shared.infrastructure.database import Database
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter(prefix="/librarians", tags=["skill-acquisition"])
logger = logging.getLogger(__name__)


async def _run_skill_acquisition_background_job(
    database: Database,
    runner_factory: Callable[
        [], SkillAcquisitionRunner | Awaitable[SkillAcquisitionRunner]
    ],
    obsidian_service_factory: Callable[
        [], ObsidianService | Awaitable[ObsidianService]
    ],
    job_id: str,
) -> None:
    """Run one acquisition job in an independently committed session.

    Args:
        database: Application database coordinator.
        runner_factory: Provider that builds a runner after session rebinding.
        obsidian_service_factory: Provider that builds the Obsidian publisher boundary.
        job_id: Durable skill-acquisition job identifier.
    """
    async with database.request_session() as session:
        try:
            runner_candidate = runner_factory()
            runner = (
                await cast(Awaitable[SkillAcquisitionRunner], runner_candidate)
                if isawaitable(runner_candidate)
                else runner_candidate
            )
            obsidian_candidate = obsidian_service_factory()
            obsidian_service = (
                await cast(Awaitable[ObsidianService], obsidian_candidate)
                if isawaitable(obsidian_candidate)
                else obsidian_candidate
            )
            await runner.run_job(
                job_id,
                artifact_publisher=ObsidianSkillArtifactPublisher(obsidian_service),
            )
        except Exception:
            # Background execution is a transaction boundary. Roll back partial
            # state and preserve the concrete exception only in operator logs.
            await session.rollback()
            logger.exception(
                "Skill acquisition background task failed",
                extra={"job_id": job_id},
            )
            raise
        await session.commit()


@router.post(
    "/skill-library/search",
    response_model=SkillCapabilitySearchResponse,
    description="Search reusable skill notes and evaluate sufficiency before acquisition.",
    status_code=status.HTTP_200_OK,
    summary="Search skill library",
)
@router_exception_status(LIBRARIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def search_skill_library(
    request: Annotated[
        SkillCapabilitySearchRequest,
        Depends(model_validate_json_body(SkillCapabilitySearchRequest)),
    ],
    obsidian_service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> SkillCapabilitySearchResponse:
    """Search existing skill artifacts before creating an acquisition job.

    Args:
        request: Normalized capability brief.
        obsidian_service: Obsidian-backed skill library search boundary.

    Returns:
        Sufficiency decision and normalized candidates.
    """
    result = await SkillLibrarySearchService(obsidian_service).search_first(
        request.to_brief()
    )
    return skill_capability_search_response(result)


@router.post(
    "/skill-acquisition-jobs",
    response_model=SkillAcquisitionJobResponse,
    description="Create a durable autonomous skill-acquisition job.",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create skill acquisition job",
)
@router_exception_status(LIBRARIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def create_skill_acquisition_job(
    request: Annotated[
        SkillAcquisitionJobRequest,
        Depends(model_validate_json_body(SkillAcquisitionJobRequest)),
    ],
    background_tasks: BackgroundTasks,
    service: Annotated[
        SkillAcquisitionService,
        Depends(Provide[ApplicationContainer.librarian.skill_acquisition_service]),
    ],
    database: Annotated[Database, Depends(Provide[ApplicationContainer.database])],
    runner_factory: Annotated[
        Callable[[], SkillAcquisitionRunner | Awaitable[SkillAcquisitionRunner]],
        Depends(
            Provide[ApplicationContainer.librarian.skill_acquisition_runner.provider]
        ),
    ],
    obsidian_service_factory: Annotated[
        Callable[[], ObsidianService | Awaitable[ObsidianService]],
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service.provider]),
    ],
) -> SkillAcquisitionJobResponse:
    """Create a durable acquisition job and queue autonomous execution.

    Args:
        request: Capability-gap request from the requesting agent.
        background_tasks: FastAPI background task coordinator.
        service: Durable skill-acquisition application service.
        database: Database coordinator for the detached task session.
        runner_factory: Deferred acquisition runner provider.
        obsidian_service_factory: Deferred artifact publication service provider.

    Returns:
        Created durable job response.
    """
    job = await service.request_job(
        prompt=request.prompt,
        agent_name=request.agent_name,
        project=request.project,
        task_summary=request.task_summary,
        provider_id=None,
        librarian_profile_id=None,
        search_snapshot=request.search_snapshot,
        acquisition_override_reason=request.acquisition_override_reason,
    )
    if job.status is SkillAcquisitionJobStatus.ACCEPTED:
        background_tasks.add_task(
            _run_skill_acquisition_background_job,
            database=database,
            runner_factory=runner_factory,
            obsidian_service_factory=obsidian_service_factory,
            job_id=job.id,
        )
    return skill_acquisition_job_response(job)


@router.get(
    "/skill-acquisition-jobs/{job_id}",
    response_model=SkillAcquisitionJobResponse,
    description="Return durable autonomous acquisition status and handoff.",
    status_code=status.HTTP_200_OK,
    summary="Get skill acquisition job",
)
@router_exception_status(LIBRARIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_skill_acquisition_job(
    job_id: str,
    service: Annotated[
        SkillAcquisitionService,
        Depends(Provide[ApplicationContainer.librarian.skill_acquisition_service]),
    ],
) -> SkillAcquisitionJobResponse:
    """Return one durable skill-acquisition job.

    Args:
        job_id: Job identifier.
        service: Durable skill-acquisition application service.

    Returns:
        Durable job status and result handoff.
    """
    job = await service.get_job(job_id)
    return skill_acquisition_job_response(job)
