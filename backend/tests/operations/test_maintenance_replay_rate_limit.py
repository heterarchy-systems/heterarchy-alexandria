"""HTTP feedback for a rate-limited fresh DLQ replay."""

from __future__ import annotations

import asyncio

from dependency_injector import providers
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import app as main_app
from app.operations.application.maintenance_job_queue import (
    MaintenanceSubmissionRateLimitError,
)
from app.operations.domain.entities.maintenance_job import MaintenanceJobSnapshot
from app.operations.interface.routers.maintenance.dead_letter_replay_router import (
    router,
)


class _RateLimitedReplay:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def replay_dead_letter(self, entry_id: str) -> MaintenanceJobSnapshot:
        self.calls.append(entry_id)
        raise MaintenanceSubmissionRateLimitError(retry_after_seconds=17)


def test_rate_limited_replay_returns_retry_after_without_publishing_a_job() -> None:
    """Exercise the actual DI-wired route at its queue effect boundary."""

    async def scenario() -> None:
        api = FastAPI()
        api.include_router(router)
        queue = _RateLimitedReplay()
        container = main_app.state.container
        with container.maintenance_job_submitter.override(providers.Object(queue)):
            async with AsyncClient(
                transport=ASGITransport(app=api, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/operations/maintenance/dead-letters/7-0/replay"
                )

        assert queue.calls == ["7-0"]
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "17"
        assert response.json() == {
            "detail": "Maintenance submission rate limit exceeded"
        }

    asyncio.run(scenario())
