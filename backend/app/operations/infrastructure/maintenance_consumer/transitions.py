"""Redis consumer transitions responsibilities."""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime

from redis.asyncio import Redis

from app.operations.application.maintenance_job_queue import (
    MaintenanceJobDelivery,
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceJobSnapshot,
)
from app.operations.infrastructure.maintenance_consumer.transition_script import (
    TRANSITION_MAINTENANCE_JOB_SCRIPT,
)
from app.operations.infrastructure.maintenance_queue.keys import status_key
from app.platform.config.redis_config import MaintenanceQueueConfig
from app.shared.types.redis_types import RedisResponse


class MaintenanceTransitionExecutor:
    """Run the existing Lua transaction with its exact argument sequence."""

    def __init__(self, client: Redis, config: MaintenanceQueueConfig) -> None:
        """Bind the borrowed Redis client and queue configuration.

        Args:
            client: Async Redis client owned by the consumer.
            config: Maintenance queue stream and key configuration.
        """
        self._client = client
        self._config = config

    async def eval_transition(
        self,
        mode: str,
        delivery: MaintenanceJobDelivery,
        snapshot: MaintenanceJobSnapshot,
        *,
        expected_status: str,
        expected_attempt: int,
        expected_history: bytes,
        expected_result: bytes = b"",
        occurred_at: datetime,
        next_history: bytes,
        result_json: bytes = b"",
        error_summary: str = "",
    ) -> RedisResponse:
        """Run one Lua-fenced maintenance state transition.

        Args:
            mode: Transition mode (`ADMIT`, `SUCCEEDED`, or `FAILED`).
            delivery: Claimed stream delivery under execution.
            snapshot: Last observed job status snapshot for CAS verification.
            expected_status: Expected status string in the Redis hash.
            expected_attempt: Expected attempt counter in the Redis hash.
            expected_history: Expected UTF-8 attempt-history JSON bytes.
            expected_result: Expected UTF-8 result JSON bytes when replaying success.
            occurred_at: Timestamp recorded for this transition.
            next_history: Updated UTF-8 attempt-history JSON bytes.
            result_json: Serialized outcome payload for `SUCCEEDED`.
            error_summary: Sanitized failure summary for `FAILED`.

        Returns:
            Raw two-element Lua reply from `TRANSITION_MAINTENANCE_JOB_SCRIPT`.

        Raises:
            MaintenanceQueueUnavailableError: If Redis eval does not return an awaitable.
        """
        operation = self._client.eval(
            TRANSITION_MAINTENANCE_JOB_SCRIPT,
            3,
            status_key(self._config, snapshot.job_id),
            self._config.stream_name,
            self._config.dead_letter_stream_name,
            mode,
            delivery.stream_id,
            snapshot.job_id,
            snapshot.kind.value,
            expected_status,
            str(expected_attempt),
            expected_history,
            expected_result,
            snapshot.source_id,
            snapshot.requested_by,
            str(snapshot.limit),
            "1" if snapshot.force else "0",
            snapshot.submitted_at.isoformat(),
            occurred_at.isoformat(),
            next_history,
            result_json,
            error_summary,
            str(self._config.max_attempts),
            str(self._config.status_ttl_seconds),
            str(self._config.max_stream_length),
            self._config.consumer_group,
        )
        if not isinstance(operation, Awaitable):
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance transition eval did not return an awaitable"
            )
        raw: RedisResponse = await operation
        return raw
