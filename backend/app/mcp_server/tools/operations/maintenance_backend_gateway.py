"""HTTP-only MCP gateways for queued maintenance jobs."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import path_segment
from app.mcp_server.type_validate.maintenance_contracts import (
    MaintenanceBatchNoteWriteToolRequest,
    MaintenanceDeadLetterIdToolRequest,
    MaintenanceDeadLetterRetireToolRequest,
    MaintenanceDeadLetterRetryToolRequest,
    MaintenanceEmbeddingReindexToolRequest,
    MaintenanceJobIdToolRequest,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceDeadLetterRetirementClassification,
)
from app.operations.interface.schemas.operations.maintenance.job_schema import (
    MaintenanceJobsRequest,
    MaintenanceJobsResponse,
)
from app.shared.serialization.orjson_codec import dumps_json
from app.shared.types.extra_types import JSONValue


async def alexandria_get_maintenance_jobs(
    client: AlexandriaApiClient, job_ids: list[str]
) -> MaintenanceJobsResponse:
    """Read one bounded batch without submitting or retrying any job.

    Args:
        client: Existing backend HTTP client.
        job_ids: Existing maintenance job identities.

    Returns:
        Current states and explicitly absent identities.
    """
    request = MaintenanceJobsRequest(job_ids=job_ids)
    payload = await client.post(
        "/operations/maintenance/jobs/batch-status", {"job_ids": request.job_ids}
    )
    return MaintenanceJobsResponse.model_validate_json(dumps_json(payload))


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


async def alexandria_submit_batch_note_write_job(
    client: AlexandriaApiClient,
    operations: list[dict[str, JSONValue]],
    requested_by: str = "mcp",
) -> JSONValue:
    """Queue one bounded asynchronous batch note write job.

    Args:
        client: Backend API client used to submit the batch write request.
        operations: JSON write operations executed by the worker.
        requested_by: Operator or automation identity recorded on the job.

    Returns:
        Decoded backend response containing the queued job snapshot.
    """
    request = MaintenanceBatchNoteWriteToolRequest(
        requested_by=requested_by,
        operations=operations,
    )
    return await client.post(
        "/operations/maintenance/batch-note-write/jobs",
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
        f"/operations/maintenance/jobs/{path_segment(request.job_id)}"
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


async def alexandria_list_maintenance_dead_letters(
    client: AlexandriaApiClient,
    limit: int = 50,
) -> JSONValue:
    """Read the newest terminal maintenance job failures.

    Args:
        client: Backend API client used to read the dead-letter endpoint.
        limit: Maximum number of dead-letter entries to return.

    Returns:
        Decoded backend response containing newest-first dead-letter entries.
    """
    return await client.get(
        "/operations/maintenance/dead-letters",
        {"limit": max(1, min(limit, 200))},
    )


async def alexandria_purge_maintenance_dead_letters(
    client: AlexandriaApiClient,
) -> JSONValue:
    """Drop every dead-letter entry after operator review.

    Args:
        client: Backend API client used to call the dead-letter purge endpoint.

    Returns:
        Decoded backend response containing the purged entry count.
    """
    return await client.delete("/operations/maintenance/dead-letters")


async def alexandria_replay_maintenance_dead_letter(
    client: AlexandriaApiClient,
    entry_id: str,
) -> JSONValue:
    """Re-enqueue the request behind one dead-letter entry as a fresh job.

    Args:
        client: Backend API client used to call the dead-letter replay endpoint.
        entry_id: Dead-letter stream entry identifier to replay.

    Returns:
        Decoded backend response containing the freshly queued job snapshot.
    """
    request = MaintenanceDeadLetterIdToolRequest(entry_id=entry_id)
    return await client.post(
        f"/operations/maintenance/dead-letters/{path_segment(request.entry_id)}/replay",
        {},
    )


async def alexandria_maintenance_dlq_inspect(
    client: AlexandriaApiClient,
    entry_id: str,
) -> JSONValue:
    """Inspect exact live or archived DLQ evidence.

    Args:
        client: Backend API client used to read DLQ evidence.
        entry_id: Dead-letter stream entry identifier to inspect.

    Returns:
        Decoded backend response containing DLQ entry evidence.
    """
    request = MaintenanceDeadLetterIdToolRequest(entry_id=entry_id)
    return await client.get(
        f"/operations/maintenance/dead-letters/{path_segment(request.entry_id)}"
    )


async def alexandria_maintenance_dlq_retry(
    client: AlexandriaApiClient,
    entry_id: str,
    dry_run: bool = False,
    reason: str = "operator retry",
) -> JSONValue:
    """Preview or same-ID retry one DLQ entry after evidence review.

    Args:
        client: Backend API client used to call the DLQ retry endpoint.
        entry_id: Dead-letter stream entry identifier to retry.
        dry_run: Whether to preview retry admissibility without requeueing.
        reason: Operator rationale recorded on the retry audit trail.

    Returns:
        Decoded backend response containing retry preview or queued job state.
    """
    request = MaintenanceDeadLetterRetryToolRequest(
        entry_id=entry_id,
        dry_run=dry_run,
        reason=reason,
    )
    return await client.post(
        f"/operations/maintenance/dead-letters/{path_segment(request.entry_id)}/retry",
        request.to_payload(),
    )


async def alexandria_maintenance_dlq_reconcile(
    client: AlexandriaApiClient,
    entry_id: str,
) -> JSONValue:
    """Read per-item mutation receipts without requeueing effects.

    Args:
        client: Backend API client used to reconcile DLQ mutation receipts.
        entry_id: Dead-letter stream entry identifier to reconcile.

    Returns:
        Decoded backend response containing per-item receipt evidence.
    """
    request = MaintenanceDeadLetterIdToolRequest(entry_id=entry_id)
    return await client.post(
        f"/operations/maintenance/dead-letters/{path_segment(request.entry_id)}/reconcile",
        {},
    )


async def alexandria_maintenance_dlq_retire(
    client: AlexandriaApiClient,
    entry_id: str,
    reason: str,
    classification: str,
    retired_by: str = "mcp",
) -> JSONValue:
    """Archive provenance and retire exactly one DLQ entry.

    Args:
        client: Backend API client used to retire the DLQ entry.
        entry_id: Dead-letter stream entry identifier to retire.
        reason: Operator rationale recorded in the retirement archive.
        classification: Terminal retirement classification code.
        retired_by: Operator or automation identity performing retirement.

    Returns:
        Decoded backend response confirming archived DLQ retirement.
    """
    request = MaintenanceDeadLetterRetireToolRequest(
        entry_id=entry_id,
        reason=reason,
        classification=MaintenanceDeadLetterRetirementClassification(classification),
        retired_by=retired_by,
    )
    return await client.post(
        f"/operations/maintenance/dead-letters/{path_segment(request.entry_id)}/retire",
        request.to_payload(),
    )
