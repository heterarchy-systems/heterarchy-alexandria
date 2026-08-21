"""MCPServer registration for queued maintenance operations."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.operations.maintenance_backend_gateway import (
    alexandria_get_maintenance_job,
    alexandria_get_maintenance_queue_status,
    alexandria_reindex_context_embeddings,
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
