"""Pure Redis key construction for the maintenance queue."""

from __future__ import annotations

import hashlib

from app.operations.domain.entities.maintenance_job import MaintenanceJobRequest
from app.platform.config.redis_config import MaintenanceQueueConfig


def status_key(config: MaintenanceQueueConfig, job_id: str) -> str:
    """Build the existing status hash key.

    Args:
        config: Typed maintenance queue configuration.
        job_id: Identifier of the maintenance job.

    Returns:
        Redis key for the job status hash.
    """
    return f"{config.status_key_prefix}:{job_id}"


def dead_letter_lifecycle_key(
    config: MaintenanceQueueConfig,
    entry_id: str,
) -> str:
    """Build the existing per-entry lifecycle reservation key.

    Args:
        config: Typed maintenance queue configuration.
        entry_id: Dead-letter stream entry identifier.

    Returns:
        Redis key for the entry lifecycle reservation.
    """
    return f"{config.dead_letter_stream_name}:lifecycle:{entry_id}"


def dedup_key(config: MaintenanceQueueConfig, request: MaintenanceJobRequest) -> str:
    """Build the existing rate-independent deduplication key.

    Args:
        config: Typed maintenance queue configuration.
        request: Validated queue submission request.

    Returns:
        Redis key for the request deduplication window.
    """
    material = "\x1f".join(
        (
            request.kind.value,
            request.requested_by,
            request.source_id,
            str(request.limit),
            "1" if request.force else "0",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{config.dedup_key_prefix}:{digest}"


def rate_key(config: MaintenanceQueueConfig, request: MaintenanceJobRequest) -> str:
    """Build the existing per-requester submission-rate key.

    Args:
        config: Typed maintenance queue configuration.
        request: Validated queue submission request.

    Returns:
        Redis key for the submission rate window.
    """
    material = f"{request.kind.value}\x1f{request.requested_by}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{config.rate_key_prefix}:maintenance:{digest}"
