"""Real Redis contracts for maintenance execution fencing and recovery."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from tests.config_test_data import (
    maintenance_configuration as maintenance_configuration,
)

from app.operations.application.maintenance_job_queue import MaintenanceJobDelivery
from app.operations.domain.entities.maintenance_job import (
    EmbeddingReindexJobResult,
    MaintenanceJobAttempt,
    MaintenanceJobRequest,
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.operations.infrastructure.maintenance_codec.history import (
    MaintenanceAttemptHistoryCodec,
)
from app.operations.infrastructure.maintenance_codec.results import (
    MaintenanceResultCodec,
)
from app.operations.infrastructure.redis_maintenance_job_consumer import (
    RedisMaintenanceJobConsumer,
)
from app.operations.infrastructure.redis_maintenance_job_queue import (
    RedisMaintenanceJobSubmitter,
)
from app.platform.config.redis_config import MaintenanceQueueConfig

pytestmark = pytest.mark.usefixtures("maintenance_configuration")


@pytest.fixture
def isolated_redis_url() -> str:
    """Require the standalone runner's loopback-only disposable Redis endpoint."""
    value = os.environ.get("REDIS_MAINTENANCE_TEST_URL")
    if value is None:
        pytest.skip(
            "run with backend/scripts/verification/run-redis-maintenance-tests.sh"
        )
    parsed = urlsplit(value)
    host = parsed.hostname
    if host is None or parsed.port is None or parsed.path not in {"", "/0"}:
        pytest.fail("Redis maintenance tests require a loopback Redis URL on DB 0")
    try:
        is_loopback = ip_address(host).is_loopback
    except ValueError:
        is_loopback = host == "localhost"
    if not is_loopback or parsed.username is not None or parsed.password is not None:
        pytest.fail("Redis maintenance tests refuse non-loopback or credentialed Redis")
    return value


def _resources(
    redis_url: str,
    *,
    max_attempts: int = 3,
) -> tuple[
    Redis,
    MaintenanceQueueConfig,
    RedisMaintenanceJobSubmitter,
    RedisMaintenanceJobConsumer,
]:
    """Create one unique key namespace in the isolated Redis instance."""
    suffix = uuid4().hex
    config = MaintenanceQueueConfig(_env_file=None).model_copy(
        update={
            "redis_url": redis_url,
            "stream_name": f"test:maintenance:{suffix}:stream",
            "dead_letter_stream_name": f"test:maintenance:{suffix}:dead",
            "consumer_group": f"test-workers-{suffix}",
            "status_key_prefix": f"test:maintenance:{suffix}:job",
            "dedup_key_prefix": f"test:maintenance:{suffix}:dedup",
            "rate_key_prefix": f"test:maintenance:{suffix}:rate",
            "max_attempts": max_attempts,
            "retry_idle_seconds": 1,
            "status_ttl_seconds": 60,
            "max_stream_length": 100,
            "submission_limit": 10,
        }
    )
    client = Redis.from_url(redis_url, decode_responses=False)
    submitter = RedisMaintenanceJobSubmitter(client, config)
    consumer = RedisMaintenanceJobConsumer(client, config, submitter)
    return client, config, submitter, consumer


def _request(source_id: str = "fixture") -> MaintenanceJobRequest:
    return MaintenanceJobRequest(
        kind=MaintenanceJobKind.EMBEDDING_REINDEX,
        requested_by="redis-fence-test",
        source_id=source_id,
        limit=5,
        force=False,
    )


async def _close(client: Redis) -> None:
    await client.aclose()


async def _wait_for_pending_idle(
    client: Redis,
    config: MaintenanceQueueConfig,
    stream_id: str,
    minimum_idle_milliseconds: int,
) -> None:
    """Wait for Redis's actual PEL idle counter to cross the reclaim threshold."""
    deadline = anyio.current_time() + 5
    while anyio.current_time() < deadline:
        pending = await client.xpending_range(
            config.stream_name,
            config.consumer_group,
            min=stream_id,
            max=stream_id,
            count=1,
        )
        if pending:
            idle = pending[0].get("time_since_delivered")
            if idle is not None and int(idle) >= minimum_idle_milliseconds:
                return
        await anyio.sleep(0.01)
    raise AssertionError(f"pending entry did not age: {stream_id}")


async def _pending_count(client: Redis, config: MaintenanceQueueConfig) -> int:
    pending = await client.xpending(config.stream_name, config.consumer_group)
    value = pending.get("pending")
    return int(value or 0)


async def _snapshot(
    submitter: RedisMaintenanceJobSubmitter,
    job_id: str,
) -> MaintenanceJobSnapshot:
    snapshot = await submitter.get(job_id)
    assert snapshot is not None
    return snapshot


def test_concurrent_admission_has_one_executor(isolated_redis_url: str) -> None:
    """One atomic status/attempt CAS admits only one concurrent worker."""

    async def scenario() -> None:
        client, config, submitter, consumer = _resources(isolated_redis_url)
        try:
            submitted = await submitter.enqueue(_request())
            delivery = await consumer.receive("worker-a")
            assert delivery is not None
            duplicate = MaintenanceJobDelivery(
                stream_id=delivery.stream_id,
                job=delivery.job,
            )
            outcomes: list[object] = []

            async def admit(candidate: MaintenanceJobDelivery) -> None:
                outcomes.append(await consumer.mark_running(candidate))

            async with anyio.create_task_group() as task_group:
                task_group.start_soon(admit, delivery)
                task_group.start_soon(admit, duplicate)
            admitted = [outcome for outcome in outcomes if isinstance(outcome, int)]
            rejected = [outcome for outcome in outcomes if not isinstance(outcome, int)]
            assert admitted == [1]
            assert len(rejected) == 1
            snapshot = await _snapshot(submitter, submitted.job_id)
            assert snapshot.status is MaintenanceJobStatus.RUNNING
            assert snapshot.attempts == 1
            assert len(snapshot.attempt_history) == 1
            assert (
                await client.ttl(f"{config.status_key_prefix}:{submitted.job_id}") == -1
            )
        finally:
            await _close(client)

    anyio.run(scenario)


def test_lost_admission_response_never_authorizes_effects(
    isolated_redis_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed admission with a lost reply remains non-executable locally."""

    async def scenario() -> None:
        client, config, submitter, consumer = _resources(isolated_redis_url)
        effect_calls = 0
        try:
            submitted = await submitter.enqueue(_request())
            delivery = await consumer.receive("worker-a")
            assert delivery is not None
            original_eval = client.eval
            reply_lost = False

            async def eval_then_lose_reply(*args: object, **kwargs: object) -> object:
                nonlocal reply_lost
                result = await original_eval(*args, **kwargs)
                if not reply_lost and args[5] == "ADMIT":
                    reply_lost = True
                    raise RedisConnectionError("simulated lost admission response")
                return result

            monkeypatch.setattr(client, "eval", eval_then_lose_reply)
            admission = await consumer.mark_running(delivery)
            if isinstance(admission, int):
                effect_calls += 1
            snapshot = await _snapshot(submitter, submitted.job_id)
            assert effect_calls == 0
            assert reply_lost is True
            assert snapshot.status is MaintenanceJobStatus.RUNNING
            assert snapshot.attempts == 1
            assert await _pending_count(client, config) == 1
        finally:
            await _close(client)

    anyio.run(scenario)


def test_lost_completion_response_resolves_from_durable_success(
    isolated_redis_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed completion is read back and acknowledged without re-execution."""

    async def scenario() -> None:
        client, config, submitter, consumer = _resources(isolated_redis_url)
        effect_calls = 0
        try:
            submitted = await submitter.enqueue(_request())
            delivery = await consumer.receive("worker-a")
            assert delivery is not None
            admission = await consumer.mark_running(delivery)
            assert isinstance(admission, int)
            effect_calls += 1
            result = EmbeddingReindexJobResult(scanned=5, updated=4, skipped=1)
            original_eval = client.eval
            reply_lost = False

            async def eval_then_lose_reply(*args: object, **kwargs: object) -> object:
                nonlocal reply_lost
                result_value = await original_eval(*args, **kwargs)
                if not reply_lost and args[5] == "SUCCEEDED":
                    reply_lost = True
                    raise RedisConnectionError("simulated lost completion response")
                return result_value

            monkeypatch.setattr(client, "eval", eval_then_lose_reply)
            published = await consumer.mark_succeeded(delivery, admission, result)
            snapshot = await _snapshot(submitter, submitted.job_id)
            assert published is True
            assert reply_lost is True
            assert effect_calls == 1
            assert snapshot.status is MaintenanceJobStatus.SUCCEEDED
            assert snapshot.result == result
            assert await _pending_count(client, config) == 0
            assert (
                0
                < await client.ttl(f"{config.status_key_prefix}:{submitted.job_id}")
                <= config.status_ttl_seconds
            )
        finally:
            await _close(client)

    anyio.run(scenario)


def test_lost_terminal_failure_response_repairs_dlq_and_ack(
    isolated_redis_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal failure reply loss is resolved from status and DLQ evidence."""

    async def scenario() -> None:
        client, config, submitter, consumer = _resources(
            isolated_redis_url,
            max_attempts=1,
        )
        try:
            submitted = await submitter.enqueue(_request())
            delivery = await consumer.receive("worker-a")
            assert delivery is not None
            admission = await consumer.mark_running(delivery)
            assert isinstance(admission, int)
            original_eval = client.eval
            reply_lost = False

            async def eval_then_lose_reply(*args: object, **kwargs: object) -> object:
                nonlocal reply_lost
                result_value = await original_eval(*args, **kwargs)
                if not reply_lost and args[5] == "FAILED":
                    reply_lost = True
                    raise RedisConnectionError("simulated lost failure response")
                return result_value

            monkeypatch.setattr(client, "eval", eval_then_lose_reply)
            terminal = await consumer.mark_failed(
                delivery,
                admission,
                "terminal failure",
            )
            snapshot = await _snapshot(submitter, submitted.job_id)
            dead_letters = await submitter.list_dead_letters(10)
            assert terminal is True
            assert reply_lost is True
            assert snapshot.status is MaintenanceJobStatus.FAILED
            assert len(dead_letters) == 1
            assert dead_letters[0].source_stream_id == delivery.stream_id
            assert await _pending_count(client, config) == 0
        finally:
            await _close(client)

    anyio.run(scenario)


@pytest.mark.parametrize("changed_field", [None, "history", "result"])
def test_succeeded_replay_repairs_ack_only_for_unchanged_evidence(
    isolated_redis_url: str,
    changed_field: str | None,
) -> None:
    """Terminal replay ACKs only when the result and history still match."""

    async def scenario() -> tuple[int, MaintenanceJobSnapshot, MaintenanceJobSnapshot]:
        client, config, submitter, consumer = _resources(isolated_redis_url)
        try:
            submitted = await submitter.enqueue(_request())
            delivery = await consumer.receive("worker-a")
            assert delivery is not None
            admission = await consumer.mark_running(delivery)
            assert isinstance(admission, int)
            running = await _snapshot(submitter, submitted.job_id)
            result = EmbeddingReindexJobResult(scanned=5, updated=5, skipped=0)
            finished_at = datetime.now(UTC)
            history = MaintenanceAttemptHistoryCodec.encode_attempt_history(
                (
                    *running.attempt_history,
                    MaintenanceJobAttempt(
                        attempt=running.attempt_history[-1].attempt,
                        status=MaintenanceJobStatus.SUCCEEDED.value,
                        occurred_at=finished_at,
                    ),
                )
            )
            status_key = f"{config.status_key_prefix}:{submitted.job_id}"
            await client.hset(
                status_key,
                mapping={
                    "status": MaintenanceJobStatus.SUCCEEDED.value,
                    "finished_at": finished_at.isoformat(),
                    "result_json": MaintenanceResultCodec.encode_embedding_result(
                        result
                    ),
                    "attempt_history_json": history,
                },
            )
            terminal = await _snapshot(submitter, submitted.job_id)
            if changed_field == "history":
                await client.hset(status_key, "attempt_history_json", b"[]")
            elif changed_field == "result":
                await client.hset(
                    status_key,
                    "result_json",
                    MaintenanceResultCodec.encode_embedding_result(
                        EmbeddingReindexJobResult(scanned=999, updated=0, skipped=999)
                    ),
                )
            replay = MaintenanceJobDelivery(
                stream_id=delivery.stream_id,
                job=terminal,
            )
            assert await consumer.mark_succeeded(replay, admission, result) is False
            await consumer.mark_running(replay)
            after = await _snapshot(submitter, submitted.job_id)
            return await _pending_count(client, config), terminal, after
        finally:
            await _close(client)

    pending, before, after = anyio.run(scenario)
    if changed_field is None:
        assert pending == 0
        assert after.result == before.result
        assert after.attempt_history == before.attempt_history
    else:
        assert pending == 1
        if changed_field == "history":
            assert after.attempt_history == ()
        else:
            assert after.result != before.result


def test_terminal_failure_replay_repairs_one_evidence_preserving_dlq_entry(
    isolated_redis_url: str,
) -> None:
    """A valid failed status repairs missing DLQ publication before its ACK."""

    async def scenario() -> None:
        client, config, submitter, consumer = _resources(
            isolated_redis_url,
            max_attempts=1,
        )
        try:
            submitted = await submitter.enqueue(_request())
            delivery = await consumer.receive("worker-a")
            assert delivery is not None
            admission = await consumer.mark_running(delivery)
            assert isinstance(admission, int)
            failed_at = datetime.now(UTC)
            running = await _snapshot(submitter, submitted.job_id)
            history = MaintenanceAttemptHistoryCodec.encode_attempt_history(
                (
                    *running.attempt_history,
                    MaintenanceJobAttempt(
                        attempt=running.attempt_history[-1].attempt,
                        status=MaintenanceJobStatus.FAILED.value,
                        occurred_at=failed_at,
                        error_summary="terminal failure",
                    ),
                )
            )
            status_key = f"{config.status_key_prefix}:{submitted.job_id}"
            await client.hset(
                status_key,
                mapping={
                    "status": MaintenanceJobStatus.FAILED.value,
                    "finished_at": failed_at.isoformat(),
                    "error_summary": "terminal failure",
                    "attempt_history_json": history,
                    "dlq_entry_id": "",
                },
            )
            terminal = await _snapshot(submitter, submitted.job_id)
            await consumer.mark_running(
                MaintenanceJobDelivery(stream_id=delivery.stream_id, job=terminal)
            )
            entries = await submitter.list_dead_letters(10)
            assert len(entries) == 1
            assert entries[0].source_stream_id == delivery.stream_id
            assert entries[0].attempt_history == terminal.attempt_history
            assert await _pending_count(client, config) == 0
            assert 0 < await client.ttl(status_key) <= config.status_ttl_seconds
            replay = MaintenanceJobDelivery(stream_id=delivery.stream_id, job=terminal)
            await consumer.mark_running(replay)
            assert len(await submitter.list_dead_letters(10)) == 1
        finally:
            await _close(client)

    anyio.run(scenario)


def test_stale_generation_after_same_id_retry_cannot_admit_or_publish(
    isolated_redis_url: str,
) -> None:
    """The new stream ID fences stale work even though retry resets attempts."""

    async def scenario() -> None:
        client, config, submitter, consumer = _resources(
            isolated_redis_url,
            max_attempts=1,
        )
        try:
            submitted = await submitter.enqueue(_request())
            first_delivery = await consumer.receive("worker-a")
            assert first_delivery is not None
            first_attempt = await consumer.mark_running(first_delivery)
            assert isinstance(first_attempt, int)
            assert (
                await consumer.mark_failed(
                    first_delivery,
                    first_attempt,
                    "terminal failure",
                )
                is True
            )
            failed = await _snapshot(submitter, submitted.job_id)
            dead_letters = await submitter.list_dead_letters(10)
            assert len(dead_letters) == 1
            retried = await submitter.retry_dead_letter(
                dead_letters[0].entry_id,
                "operator-approved retry",
            )
            assert retried.job_id == submitted.job_id
            assert retried.stream_id != first_delivery.stream_id
            assert retried.attempts == 0
            assert (
                await client.ttl(f"{config.status_key_prefix}:{submitted.job_id}") == -1
            )
            stale_admission = await consumer.mark_running(first_delivery)
            assert not isinstance(stale_admission, int)
            unchanged = await _snapshot(submitter, submitted.job_id)
            assert unchanged.status is MaintenanceJobStatus.QUEUED
            assert unchanged.stream_id == retried.stream_id
            assert unchanged.attempts == 0
            stale_outcome = await consumer.mark_succeeded(
                first_delivery,
                first_attempt,
                EmbeddingReindexJobResult(scanned=5, updated=5, skipped=0),
            )
            assert stale_outcome is False
            after_stale_outcome = await _snapshot(submitter, submitted.job_id)
            assert after_stale_outcome.status is MaintenanceJobStatus.QUEUED
            assert after_stale_outcome.stream_id == retried.stream_id
            assert after_stale_outcome.attempts == 0
            assert (
                await consumer.mark_failed(
                    first_delivery,
                    first_attempt,
                    "stale failure",
                )
                is None
            )
            assert failed.status is MaintenanceJobStatus.FAILED
        finally:
            await _close(client)

    anyio.run(scenario)


def test_stale_attempt_cannot_admit_or_overwrite_retry_progress(
    isolated_redis_url: str,
) -> None:
    """Attempt CAS rejects an old RETRYING snapshot after the next admission."""

    async def scenario() -> None:
        client, config, submitter, consumer = _resources(isolated_redis_url)
        try:
            submitted = await submitter.enqueue(_request())
            status_key = f"{config.status_key_prefix}:{submitted.job_id}"
            assert await client.ttl(status_key) == -1
            first_delivery = await consumer.receive("worker-a")
            assert first_delivery is not None
            first_attempt = await consumer.mark_running(first_delivery)
            assert isinstance(first_attempt, int)
            assert (
                await consumer.mark_failed(
                    first_delivery,
                    first_attempt,
                    "transient failure",
                )
                is False
            )
            assert await client.ttl(status_key) == -1
            retry_snapshot = await _snapshot(submitter, submitted.job_id)
            retry_delivery = MaintenanceJobDelivery(
                stream_id=first_delivery.stream_id,
                job=retry_snapshot,
            )
            next_attempt = await consumer.mark_running(retry_delivery)
            assert isinstance(next_attempt, int)
            assert next_attempt == 2
            assert await client.ttl(status_key) == -1
            stale = await consumer.mark_running(retry_delivery)
            assert not isinstance(stale, int)
            assert (
                await consumer.mark_failed(
                    retry_delivery,
                    first_attempt,
                    "stale attempt failure",
                )
                is None
            )
            final_snapshot = await _snapshot(submitter, submitted.job_id)
            assert final_snapshot.status is MaintenanceJobStatus.RUNNING
            assert final_snapshot.attempts == 2
            assert await _pending_count(client, config) == 1
        finally:
            await _close(client)

    anyio.run(scenario)


@pytest.mark.parametrize("corrupt", [False, True])
def test_missing_or_corrupt_state_is_not_acknowledged_or_reconstructed(
    isolated_redis_url: str,
    corrupt: bool,
) -> None:
    """An absent or malformed status hash remains pending and unchanged."""

    async def scenario() -> None:
        client, config, submitter, consumer = _resources(isolated_redis_url)
        try:
            submitted = await submitter.enqueue(_request())
            status_key = f"{config.status_key_prefix}:{submitted.job_id}"
            await client.delete(status_key)
            if corrupt:
                await client.hset(status_key, mapping={"status": "RUNNING"})
            delivery = await consumer.receive("worker-a")
            assert delivery is None
            assert await _pending_count(client, config) == 1
            fields = await client.hgetall(status_key)
            assert fields == ({b"status": b"RUNNING"} if corrupt else {})
        finally:
            await _close(client)

    anyio.run(scenario)


def test_running_past_reclaim_idle_is_never_reexecuted(
    isolated_redis_url: str,
) -> None:
    """XAUTOCLAIM of idle RUNNING work cannot authorize a second execution."""

    async def scenario() -> None:
        client, config, submitter, consumer = _resources(isolated_redis_url)
        effect_calls = 0
        try:
            submitted = await submitter.enqueue(_request())
            delivery = await consumer.receive("worker-a")
            assert delivery is not None
            first_admission = await consumer.mark_running(delivery)
            assert isinstance(first_admission, int)
            effect_calls += 1
            await _wait_for_pending_idle(client, config, delivery.stream_id, 1000)
            reclaimed = await consumer.receive("worker-b")
            assert reclaimed is None
            snapshot = await _snapshot(submitter, submitted.job_id)
            second_admission = await consumer.mark_running(
                MaintenanceJobDelivery(stream_id=delivery.stream_id, job=snapshot)
            )
            if isinstance(second_admission, int):
                effect_calls += 1
            assert second_admission is not None
            assert not isinstance(second_admission, int)
            assert effect_calls == 1
            assert snapshot.status is MaintenanceJobStatus.RUNNING
            assert snapshot.attempts == 1
            assert len(snapshot.attempt_history) == 1
            assert await _pending_count(client, config) == 1
        finally:
            await _close(client)

    anyio.run(scenario)


def test_continuously_reclaimable_running_work_falls_through_to_fresh_work(
    isolated_redis_url: str,
) -> None:
    """Fresh work progresses even when every receive reclaims unresolved work."""

    async def scenario() -> None:
        client, config, submitter, consumer = _resources(isolated_redis_url)
        try:
            pending_deliveries: list[MaintenanceJobDelivery] = []
            for index in range(3):
                await submitter.enqueue(_request(f"running-{index}"))
                delivery = await consumer.receive("worker-a")
                assert delivery is not None
                assert isinstance(await consumer.mark_running(delivery), int)
                pending_deliveries.append(delivery)
            for index in range(4):
                fresh = await submitter.enqueue(_request(f"fresh-{index}"))
                # Model a backlog whose traversal exceeds the idle interval:
                # every receive sees RUNNING work eligible for XAUTOCLAIM.
                await client.xclaim(
                    config.stream_name,
                    config.consumer_group,
                    "worker-a",
                    min_idle_time=0,
                    message_ids=[item.stream_id for item in pending_deliveries],
                    idle=1001,
                    justid=True,
                )
                delivery = await consumer.receive("worker-b")
                assert delivery is not None
                assert delivery.job.job_id == fresh.job_id
                assert isinstance(await consumer.mark_running(delivery), int)
                pending_deliveries.append(delivery)
            assert await _pending_count(client, config) == len(pending_deliveries)
        finally:
            await _close(client)

    anyio.run(scenario)
