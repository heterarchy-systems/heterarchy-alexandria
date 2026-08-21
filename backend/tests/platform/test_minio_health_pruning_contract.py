"""Contracts proving MINIO is not part of platform health readiness."""

from __future__ import annotations

from app.platform.lifecycle.dependency_health_enums import PlatformDependency
from app.platform.lifecycle.state import LifecycleState
from app.platform.schemas.health_schema import (
    heartbeat_payload_from_snapshot,
    ready_payload_from_snapshot,
)


def test_health_payloads_do_not_expose_minio_dependency() -> None:
    """Readiness/heartbeat should describe core runtime dependencies only."""
    lifecycle = LifecycleState()
    lifecycle.dependencies.mark_healthy(PlatformDependency.DATABASE)
    lifecycle.mark_running()
    snapshot = lifecycle.snapshot()

    ready_payload = ready_payload_from_snapshot(snapshot).model_dump()
    heartbeat_payload = heartbeat_payload_from_snapshot(snapshot).model_dump()

    assert "minio" not in ready_payload["checks"]
    assert "minio" not in heartbeat_payload["heartbeat"]
