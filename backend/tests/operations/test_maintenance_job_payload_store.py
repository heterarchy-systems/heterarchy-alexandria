"""Maintenance job payload staging store contracts."""

from __future__ import annotations

import os
import uuid

import anyio

from app.operations.infrastructure.maintenance_job_payload_store import (
    MaintenanceJobPayloadStore,
)
from app.shared.infrastructure.database import Database


def test_payload_store_roundtrips_and_deletes() -> None:
    """Staged payloads load by id and disappear after deletion."""

    async def scenario() -> tuple[dict | None, dict | None]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        payload_id = uuid.uuid4().hex
        body = {"requested_by": "mcp", "operations": [{"op": "update"}]}
        try:
            async with database.request_session() as session:
                store = MaintenanceJobPayloadStore(session)
                await store.save(payload_id, "batch_note_write", body)
            async with database.request_session() as session:
                loaded = await MaintenanceJobPayloadStore(session).load(payload_id)
            async with database.request_session() as session:
                await MaintenanceJobPayloadStore(session).delete(payload_id)
            async with database.request_session() as session:
                deleted = await MaintenanceJobPayloadStore(session).load(payload_id)
            return loaded, deleted
        finally:
            await database.shutdown()

    loaded, deleted = anyio.run(scenario)

    assert loaded is not None
    assert loaded["operations"] == [{"op": "update"}]
    assert deleted is None


def test_payload_store_loads_unknown_as_none() -> None:
    """An unknown payload id loads as None without raising."""

    async def scenario() -> dict | None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.request_session() as session:
                return await MaintenanceJobPayloadStore(session).load("missing")
        finally:
            await database.shutdown()

    assert anyio.run(scenario) is None
