"""Dependency-injector container for librarian bounded context."""

from __future__ import annotations

from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections.domain.repositories.librarian_repository import (
    ILibrarianProviderRepository,
    IProviderSecretRepository,
)
from app.connections.infrastructure.librarians.openai_delegate_executor import (
    OpenAIProviderDelegateExecutor,
)
from app.connections.infrastructure.librarians.openai_skill_acquisition_executor import (
    OpenAISkillAcquisitionExecutor,
)
from app.librarian.application.agent_service import AgentService
from app.librarian.application.delegation.hermes_collaboration_service import (
    HermesCollaborationService,
)
from app.librarian.application.skill_acquisition.skill_acquisition_runner import (
    SkillAcquisitionRunner,
)
from app.librarian.application.skill_acquisition.skill_acquisition_service import (
    SkillAcquisitionService,
)
from app.librarian.infrastructure.repositories.agent_repository import (
    SqlAlchemyAgentRepository,
)
from app.librarian.infrastructure.repositories.skill_acquisition_job_repository import (
    SqlAlchemySkillAcquisitionJobRepository,
)


class LibrarianContainer(containers.DeclarativeContainer):
    """Container for librarian profiles, routing, and collaboration."""

    db_session = providers.Dependency(instance_of=AsyncSession)
    agent_repo = providers.Factory(SqlAlchemyAgentRepository, session=db_session)
    skill_acquisition_job_repo = providers.Factory(
        SqlAlchemySkillAcquisitionJobRepository,
        session=db_session,
    )
    librarian_provider_repo = providers.Dependency(
        instance_of=ILibrarianProviderRepository
    )
    provider_secret_repo = providers.Dependency(instance_of=IProviderSecretRepository)
    external_api_rate_limiter = providers.Dependency()
    delegate_executor = providers.Factory(
        OpenAIProviderDelegateExecutor,
        secret_repo=provider_secret_repo,
        rate_limiter=external_api_rate_limiter,
    )
    skill_acquisition_service = providers.Factory(
        SkillAcquisitionService,
        repository=skill_acquisition_job_repo,
        provider_repo=librarian_provider_repo,
        secret_repo=provider_secret_repo,
    )
    skill_acquisition_executor = providers.Factory(
        OpenAISkillAcquisitionExecutor,
        provider_repo=librarian_provider_repo,
        secret_repo=provider_secret_repo,
        rate_limiter=external_api_rate_limiter,
    )
    skill_acquisition_runner = providers.Factory(
        SkillAcquisitionRunner,
        service=skill_acquisition_service,
        executor=skill_acquisition_executor,
    )
    agent_service = providers.Factory(
        AgentService,
        repository=agent_repo,
        provider_repo=librarian_provider_repo,
        secret_repo=provider_secret_repo,
    )
    hermes_collaboration_service = providers.Factory(
        HermesCollaborationService,
        provider_repo=librarian_provider_repo,
        agent_repo=agent_repo,
        secret_repo=provider_secret_repo,
        delegate_executor=delegate_executor,
    )
