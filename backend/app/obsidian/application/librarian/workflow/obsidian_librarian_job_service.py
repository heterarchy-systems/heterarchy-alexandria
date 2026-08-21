"""In-process Obsidian librarian execution job service."""

from __future__ import annotations

from datetime import UTC, datetime

from app.obsidian.application.librarian.delegation.obsidian_librarian_delegation import (
    ObsidianLibrarianDelegateService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianVaultMoveApplyRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianLibrarianJob,
    ObsidianVaultMoveReport,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianLibrarianJobStatus
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianNotFoundError
from app.shared.infrastructure.database import Database
from app.shared.infrastructure.identifiers import new_uuid

VAULT_MOVE_OPERATION = "vault_move"


class ObsidianLibrarianJobService:
    """Track best-effort in-process librarian jobs.

    Job status lives in the current service process only; move reports remain
    durable vault files, but the registry is not restart-durable.
    """

    def __init__(
        self,
        database: Database,
        vault_config_store: ObsidianVaultConfigStore,
        delegate_service: ObsidianLibrarianDelegateService | None = None,
    ) -> None:
        """Initialize the best-effort in-process job registry.

        Args:
            database: Application database coordinator used to open owned job sessions.
            vault_config_store: Runtime Obsidian vault configuration store.
            delegate_service: Optional provider-backed librarian delegate service.
        """
        self._database = database
        self._vault_config_store = vault_config_store
        self._delegate_service = delegate_service
        self._jobs: dict[str, ObsidianLibrarianJob] = {}

    def create_vault_move_job(self) -> ObsidianLibrarianJob:
        """Create a pending vault move job.

        Returns:
            Pending job status snapshot.
        """
        current = datetime.now(UTC)
        job = ObsidianLibrarianJob(
            job_id=f"obsidian_job_{new_uuid()}",
            status=ObsidianLibrarianJobStatus.PENDING,
            operation=VAULT_MOVE_OPERATION,
            report=None,
            error_message=None,
            created_at=current,
            updated_at=current,
        )
        self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> ObsidianLibrarianJob:
        """Read one job status snapshot.

        Args:
            job_id: Job id returned by create.

        Returns:
            Job status snapshot.
        """
        job = self._jobs.get(job_id)
        if job is None:
            raise ObsidianNotFoundError(f"Obsidian librarian job not found: {job_id}")
        return job

    def get_report(self, job_id: str) -> ObsidianVaultMoveReport:
        """Read one completed job report.

        Args:
            job_id: Job id returned by create.

        Returns:
            Completed move report.
        """
        job = self.get_job(job_id)
        if job.report is None:
            raise ObsidianNotFoundError(
                f"Obsidian librarian job report not available: {job_id}"
            )
        return job.report

    async def run_vault_move_job(
        self,
        job_id: str,
        request: ObsidianVaultMoveApplyRequest,
    ) -> ObsidianLibrarianJob:
        """Execute a vault move job with an owned session boundary.

        Args:
            job_id: Existing pending job id.
            request: Safe move application request.

        Returns:
            Terminal job status snapshot.
        """
        self._set_job(job_id, status=ObsidianLibrarianJobStatus.RUNNING)
        async with self._database.session_factory()() as session:
            try:
                obsidian_service = ObsidianService(
                    repository=SqlAlchemyObsidianIndexRepository(session=session),
                    vault_config_store=self._vault_config_store,
                    delegate_service=self._delegate_service,
                )
                report = await obsidian_service.apply_vault_moves(request)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                return self._set_job(
                    job_id,
                    status=ObsidianLibrarianJobStatus.FAILED,
                    error_message=str(exc),
                )
        return self._set_job(
            job_id,
            status=ObsidianLibrarianJobStatus.SUCCEEDED,
            report=report,
        )

    def _set_job(
        self,
        job_id: str,
        status: ObsidianLibrarianJobStatus,
        report: ObsidianVaultMoveReport | None = None,
        error_message: str | None = None,
    ) -> ObsidianLibrarianJob:
        current = datetime.now(UTC)
        previous = self.get_job(job_id)
        job = ObsidianLibrarianJob(
            job_id=previous.job_id,
            status=status,
            operation=previous.operation,
            report=previous.report if report is None else report,
            error_message=error_message,
            created_at=previous.created_at,
            updated_at=current,
        )
        self._jobs[job_id] = job
        return job
