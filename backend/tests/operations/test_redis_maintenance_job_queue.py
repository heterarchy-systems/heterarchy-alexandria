"""Redis Streams maintenance queue contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import anyio
import pytest
from app.operations.application.maintenance_job_queue import (
    MaintenanceJobDelivery,
    MaintenanceSubmissionRateLimitError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.operations.infrastructure.redis_maintenance_job_consumer import (
    RedisMaintenanceJobConsumer,
)
from app.operations.infrastructure.redis_maintenance_job_queue import (
    RedisMaintenanceJobSubmitter,
    create_maintenance_worker_client,
)
from app.platform.config.maintenance_queue_config import MaintenanceQueueConfig
from redis.asyncio import Redis


class _FakeRedis:
    def __init__(self) -> None:
        self.eval_response: object = ["QUEUED", "job-1", "1-0"]
        self.status_fields = _status_fields()
        self.hset_calls: list[dict[str, str]] = []
        self.xack_calls: list[tuple[str, str, str]] = []
        self.xadd_calls: list[tuple[str, dict[str, str], int, bool]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.attempt = 1

    async def eval(self, *_args: object) -> object:
        return self.eval_response

    async def hgetall(self, _key: str) -> dict[str, str]:
        return dict(self.status_fields)

    async def hincrby(self, _key: str, _field: str, _amount: int) -> int:
        return self.attempt

    async def hset(
        self,
        _key: str,
        mapping: dict[str, str],
    ) -> int:
        self.hset_calls.append(dict(mapping))
        return len(mapping)

    async def expire(self, key: str, seconds: int) -> bool:
        self.expire_calls.append((key, seconds))
        return True

    async def xack(self, stream: str, group: str, stream_id: str) -> int:
        self.xack_calls.append((stream, group, stream_id))
        return 1

    async def xadd(
        self,
        stream: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        self.xadd_calls.append((stream, dict(fields), maxlen, approximate))
        return "2-0"


def test_enqueue_returns_queued_snapshot() -> None:
    """A successful Lua result should resolve the persisted job snapshot."""

    async def scenario() -> MaintenanceJobSnapshot:
        fake = _FakeRedis()
        queue = _submitter(fake)
        return await queue.enqueue(_request())

    snapshot = anyio.run(scenario)

    assert snapshot.job_id == "job-1"
    assert snapshot.status is MaintenanceJobStatus.QUEUED
    assert snapshot.deduplicated is False


def test_enqueue_returns_existing_snapshot_for_deduplication() -> None:
    """A matching cooldown key should return the existing job id."""

    async def scenario() -> MaintenanceJobSnapshot:
        fake = _FakeRedis()
        fake.eval_response = ["DEDUPLICATED", "job-1", ""]
        queue = _submitter(fake)
        return await queue.enqueue(_request())

    snapshot = anyio.run(scenario)

    assert snapshot.job_id == "job-1"
    assert snapshot.deduplicated is True


def test_enqueue_exposes_retry_after_when_submission_budget_is_exceeded() -> None:
    """The API layer should receive an explicit Redis rate-limit delay."""

    async def scenario() -> None:
        fake = _FakeRedis()
        fake.eval_response = ["RATE_LIMITED", "42", ""]
        queue = _submitter(fake)
        with pytest.raises(MaintenanceSubmissionRateLimitError) as captured:
            await queue.enqueue(_request())
        assert captured.value.retry_after_seconds == 42

    anyio.run(scenario)


def test_nonterminal_failure_remains_pending_for_xautoclaim_retry() -> None:
    """A retryable failure should not acknowledge the Streams delivery."""

    async def scenario() -> tuple[bool, _FakeRedis]:
        fake = _FakeRedis()
        queue = _consumer(fake)
        terminal = await queue.mark_failed(
            _delivery(),
            attempt=1,
            error_summary="transient",
        )
        return terminal, fake

    terminal, fake = anyio.run(scenario)

    assert terminal is False
    assert fake.xack_calls == []
    assert fake.xadd_calls == []
    assert fake.hset_calls[-1]["status"] == MaintenanceJobStatus.RETRYING.value


def test_terminal_failure_is_dead_lettered_and_acknowledged() -> None:
    """The configured final attempt should move evidence to the dead-letter stream."""

    async def scenario() -> tuple[bool, _FakeRedis]:
        fake = _FakeRedis()
        queue = _consumer(fake)
        terminal = await queue.mark_failed(
            _delivery(),
            attempt=3,
            error_summary="permanent",
        )
        return terminal, fake

    terminal, fake = anyio.run(scenario)

    assert terminal is True
    stream_name, fields, maxlen, approximate = fake.xadd_calls[-1]
    assert stream_name == "alexandria:maintenance:dead:v1"
    assert fields["job_id"] == "job-1"
    assert maxlen == 10000
    assert approximate is True
    assert fake.xack_calls[-1][-1] == "1-0"
    assert fake.hset_calls[-1]["status"] == MaintenanceJobStatus.FAILED.value


def test_worker_client_read_timeout_has_headroom_above_stream_block() -> None:
    """Blocking Stream reads should not race a nearly identical socket timeout."""
    client = create_maintenance_worker_client(
        MaintenanceQueueConfig.model_validate(
            {
                "SERVICE_REDIS_URL": "redis://redis:6379/0",
                "block_milliseconds": 1000,
            }
        )
    )

    assert client.connection_pool.connection_kwargs["socket_timeout"] == 10.0


def _submitter(fake: _FakeRedis) -> RedisMaintenanceJobSubmitter:
    return RedisMaintenanceJobSubmitter(
        client=cast(Redis, fake),
        config=_config(),
    )


def _consumer(fake: _FakeRedis) -> RedisMaintenanceJobConsumer:
    submitter = _submitter(fake)
    return RedisMaintenanceJobConsumer(
        client=cast(Redis, fake),
        config=_config(),
        submitter=submitter,
    )


def _config() -> MaintenanceQueueConfig:
    return MaintenanceQueueConfig(
        redis_url="redis://redis:6379/0",
        max_attempts=3,
    )


def _request() -> MaintenanceJobRequest:
    return MaintenanceJobRequest(
        kind=MaintenanceJobKind.EMBEDDING_REINDEX,
        requested_by="manual",
        source_id="scheduler-1",
        limit=250,
        force=False,
    )


def _delivery() -> MaintenanceJobDelivery:
    return MaintenanceJobDelivery(
        stream_id="1-0",
        job=MaintenanceJobSnapshot(
            job_id="job-1",
            kind=MaintenanceJobKind.EMBEDDING_REINDEX,
            status=MaintenanceJobStatus.RUNNING,
            requested_by="manual",
            source_id="scheduler-1",
            limit=250,
            force=False,
            attempts=1,
            submitted_at=datetime(2026, 8, 7, tzinfo=UTC),
            stream_id="1-0",
        ),
    )


def _status_fields() -> dict[str, str]:
    return {
        "job_id": "job-1",
        "kind": MaintenanceJobKind.EMBEDDING_REINDEX.value,
        "status": MaintenanceJobStatus.QUEUED.value,
        "requested_by": "manual",
        "source_id": "scheduler-1",
        "limit": "250",
        "force": "0",
        "attempts": "0",
        "submitted_at": "2026-08-07T00:00:00+00:00",
        "stream_id": "1-0",
        "result_json": "",
        "error_summary": "",
    }
