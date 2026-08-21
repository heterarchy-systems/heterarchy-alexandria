"""HTTP-only MCP gateways for queued maintenance jobs."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import _path_segment
from app.mcp_server.type_validate.maintenance_contracts import (
    MaintenanceEmbeddingReindexToolRequest,
    MaintenanceJobIdToolRequest,
)
from app.shared.types.extra_types import JSONValue


async def alexandria_reindex_context_embeddings(
    client: AlexandriaApiClient,
    requested_by: str = "mcp",
    source_id: str = "manual",
    limit: int = 250,
    force: bool = False,
) -> JSONValue:
    """Queue one bounded Context embedding reindex job.

    Args:
        client: Backend API client used to submit the maintenance request.
        requested_by: Operator or automation identity recorded on the job.
        source_id: Stable source identifier used for duplicate suppression.
        limit: Maximum number of Context chunks to process.
        force: Whether matching embeddings should be rebuilt.

    Returns:
        Decoded backend response containing the queued job snapshot.
    """
    request = MaintenanceEmbeddingReindexToolRequest(
        requested_by=requested_by,
        source_id=source_id,
        limit=limit,
        force=force,
    )
    return await client.post(
        "/operations/maintenance/embedding-reindex/jobs",
        request.to_payload(),
    )


async def alexandria_get_maintenance_job(
    client: AlexandriaApiClient,
    job_id: str,
) -> JSONValue:
    """Read one queued maintenance job lifecycle snapshot.

    Args:
        client: Backend API client used to read the job endpoint.
        job_id: Maintenance job identifier returned by queue submission.

    Returns:
        Decoded backend response containing the job lifecycle snapshot.
    """
    request = MaintenanceJobIdToolRequest(job_id=job_id)
    return await client.get(
        f"/operations/maintenance/jobs/{_path_segment(request.job_id)}"
    )


async def alexandria_get_maintenance_queue_status(
    client: AlexandriaApiClient,
) -> JSONValue:
    """Read aggregate Redis Streams backlog and worker evidence.

    Args:
        client: Backend API client used to read the queue status endpoint.

    Returns:
        Decoded backend response containing bounded queue evidence.
    """
    return await client.get("/operations/maintenance/queue/status")
