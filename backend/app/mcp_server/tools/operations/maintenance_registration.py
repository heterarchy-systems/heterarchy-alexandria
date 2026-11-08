"""MCPServer registration for queued maintenance operations."""

from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.operations.maintenance_backend_gateway import (
    alexandria_get_maintenance_job,
    alexandria_get_maintenance_jobs,
    alexandria_get_maintenance_queue_status,
    alexandria_list_maintenance_dead_letters,
    alexandria_maintenance_dlq_inspect,
    alexandria_maintenance_dlq_reconcile,
    alexandria_maintenance_dlq_retire,
    alexandria_maintenance_dlq_retry,
    alexandria_purge_maintenance_dead_letters,
    alexandria_reindex_context_embeddings,
    alexandria_replay_maintenance_dead_letter,
    alexandria_submit_batch_note_write_job,
)
from app.operations.interface.schemas.operations.maintenance.job_schema import (
    MaintenanceJobsResponse,
)
from app.shared.types.extra_types import JSONValue


def register_maintenance_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register asynchronous queue submission and status tools.

    Args:
        server: MCP server receiving the maintenance tool registrations.
        api_client: Backend API client shared by the registered tool closures.
    """

    @server.tool(name="alexandria_get_maintenance_jobs")
    async def get_maintenance_jobs_tool(
        job_ids: Annotated[list[str], Field(min_length=1, max_length=50)],
    ) -> MaintenanceJobsResponse:
        """Read up to fifty maintenance jobs in one call.

        Args:
            job_ids: Job identities returned by submission.

        Returns:
            Mixed lifecycle snapshots and absent identities, without retry.
        """
        return await alexandria_get_maintenance_jobs(api_client, job_ids)

    @server.tool(name="alexandria_reindex_context_embeddings")
    async def reindex_context_embeddings_tool(
        requested_by: str = "mcp",
        source_id: str = "manual",
        limit: int = 250,
        force: bool = False,
    ) -> JSONValue:
        """Queue a bounded embedding reindex; poll the returned job id for completion.

        Args:
            requested_by: Operator or automation identity recorded on the job.
            source_id: Stable source identifier used for duplicate suppression.
            limit: Maximum number of Context chunks to process.
            force: Whether matching embeddings should be rebuilt.

        Returns:
            Queued maintenance job payload returned by the backend.
        """
        return await alexandria_reindex_context_embeddings(
            api_client,
            requested_by,
            source_id,
            limit,
            force,
        )

    @server.tool(name="alexandria_get_maintenance_job")
    async def get_maintenance_job_tool(job_id: str) -> JSONValue:
        """Read one maintenance job's queue, retry, success, or failure state.

        Args:
            job_id: Maintenance job identifier returned by queue submission.

        Returns:
            Current maintenance job lifecycle payload.
        """
        return await alexandria_get_maintenance_job(api_client, job_id)

    @server.tool(name="alexandria_get_maintenance_queue_status")
    async def get_maintenance_queue_status_tool() -> JSONValue:
        """Read Redis Streams backlog, pending deliveries, consumers, and DLQ size.

        Returns:
            Current bounded maintenance queue status payload.
        """
        return await alexandria_get_maintenance_queue_status(api_client)

    @server.tool(name="alexandria_list_maintenance_dead_letters")
    async def list_maintenance_dead_letters_tool(limit: int = 50) -> JSONValue:
        """Read the newest terminal maintenance job failures for review.

        Args:
            limit: Maximum number of dead-letter entries to return.

        Returns:
            Newest-first dead-letter entries with failure evidence.
        """
        return await alexandria_list_maintenance_dead_letters(api_client, limit)

    @server.tool(name="alexandria_purge_maintenance_dead_letters")
    async def purge_maintenance_dead_letters_tool() -> JSONValue:
        """Explicit bulk administrative retention purge of every DLQ entry.

        Normal cleanup uses inspect, retry/reconcile, then provenance-preserving
        retire. This purge irreversibly drops live DLQ evidence.

        Returns:
            Purged dead-letter entry count returned by the backend.
        """
        return await alexandria_purge_maintenance_dead_letters(api_client)

    @server.tool(name="alexandria_replay_maintenance_dead_letter")
    async def replay_maintenance_dead_letter_tool(entry_id: str) -> JSONValue:
        """Re-enqueue one dead-letter entry's original request as a fresh job.

        Args:
            entry_id: Dead-letter stream entry identifier returned by listing.

        Returns:
            Freshly queued replacement maintenance job payload.
        """
        return await alexandria_replay_maintenance_dead_letter(api_client, entry_id)

    @server.tool(name="alexandria_maintenance_dlq_inspect")
    async def maintenance_dlq_inspect_tool(entry_id: str) -> JSONValue:
        """Inspect exact live or archived maintenance DLQ evidence."""
        return await alexandria_maintenance_dlq_inspect(api_client, entry_id)

    @server.tool(name="alexandria_maintenance_dlq_retry")
    async def maintenance_dlq_retry_tool(
        entry_id: str,
        dry_run: bool = False,
        reason: str = "operator retry",
    ) -> JSONValue:
        """Preview or retry a DLQ entry under its original identity."""
        return await alexandria_maintenance_dlq_retry(
            api_client,
            entry_id,
            dry_run,
            reason,
        )

    @server.tool(name="alexandria_maintenance_dlq_reconcile")
    async def maintenance_dlq_reconcile_tool(entry_id: str) -> JSONValue:
        """Read batch note mutation receipts for one DLQ entry."""
        return await alexandria_maintenance_dlq_reconcile(api_client, entry_id)

    @server.tool(name="alexandria_maintenance_dlq_retire")
    async def maintenance_dlq_retire_tool(
        entry_id: str,
        reason: str,
        classification: str,
        retired_by: str = "mcp",
    ) -> JSONValue:
        """Archive provenance and retire one DLQ entry."""
        return await alexandria_maintenance_dlq_retire(
            api_client,
            entry_id,
            reason,
            classification,
            retired_by,
        )

    @server.tool(name="alexandria_submit_batch_note_write_job")
    async def submit_batch_note_write_job_tool(
        operations: list[dict[str, JSONValue]],
        requested_by: str = "mcp",
    ) -> JSONValue:
        """Queue a bounded batch note write executed asynchronously by the worker.

        Args:
            operations: JSON write operations; each carries op, title, body,
                relative_path, and the CAS expected_content_hash.
            requested_by: Operator or automation identity recorded on the job.

        Returns:
            Queued maintenance job payload; poll the job id for per-item
            CAS outcomes.
        """
        return await alexandria_submit_batch_note_write_job(
            api_client,
            operations,
            requested_by,
        )
