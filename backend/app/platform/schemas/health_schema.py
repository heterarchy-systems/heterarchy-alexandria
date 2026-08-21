"""Health check endpoint response payload models."""

from __future__ import annotations

from app.platform.lifecycle.dependency_health_enums import DependencyHealthStatus
from app.platform.lifecycle.lifecycle_enums import LifecycleStatus
from app.platform.lifecycle.snapshot import LifecycleSnapshot
from app.shared.schemas.common_schemas import StrictSchemaModel
from pydantic import ConfigDict, StrictBool, StrictStr


class HealthPayloadModel(StrictSchemaModel):
    """Common Pydantic settings shared by health payload models."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class LiveHealthPayload(HealthPayloadModel):
    """Response payload for process liveness."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"status": "ok"},
            ],
        },
    )

    status: StrictStr


class ReadyHealthChecksPayload(HealthPayloadModel):
    """Dependency check status used by readiness endpoint."""

    app: StrictStr
    redis: StrictStr
    database: StrictStr


class ReadyHealthPayload(HealthPayloadModel):
    """Response payload for readiness endpoint."""

    status: StrictStr
    checks: ReadyHealthChecksPayload
    reason: StrictStr | None


class HeartbeatDetailsPayload(HealthPayloadModel):
    """Response payload with detailed heartbeat status."""

    app: StrictStr
    redis: StrictStr
    database: StrictStr
    lifecycle: StrictStr
    draining: StrictBool
    drain_reason: StrictStr | None
    started_at: StrictStr
    drain_started_at: StrictStr | None


class HeartbeatHealthPayload(HealthPayloadModel):
    """Wrapper payload for heartbeat response."""

    heartbeat: HeartbeatDetailsPayload


def app_check_from_status(status: LifecycleStatus) -> str:
    """Convert lifecycle status to an app check string.

    Args:
        status: See function signature.

    Returns:
        Return value.
    """
    if status is LifecycleStatus.RUNNING:
        return "ok"
    return status.value


def dependency_check_from_status(status: DependencyHealthStatus) -> str:
    """Convert dependency status to a check string.

    Args:
        status: See function signature.

    Returns:
        Return value.
    """
    return status.value


def ready_payload_from_snapshot(snapshot: LifecycleSnapshot) -> ReadyHealthPayload:
    """Build ready payload from a lifecycle snapshot.

    Args:
        snapshot: See function signature.

    Returns:
        Return value.
    """
    app_check = app_check_from_status(snapshot.status)
    redis_check = dependency_check_from_status(snapshot.redis_status)
    database_check = dependency_check_from_status(snapshot.database_status)
    if snapshot.ready:
        return ReadyHealthPayload(
            status="ok",
            checks=ReadyHealthChecksPayload(
                app=app_check,
                redis=redis_check,
                database=database_check,
            ),
            reason=None,
        )

    status = "draining" if snapshot.draining else "not_ready"
    reason = snapshot.drain_reason
    if reason is None:
        reason = _dependency_unavailable_reason(snapshot)
    return ReadyHealthPayload(
        status=status,
        checks=ReadyHealthChecksPayload(
            app=app_check,
            redis=redis_check,
            database=database_check,
        ),
        reason=reason,
    )


def heartbeat_payload_from_snapshot(
    snapshot: LifecycleSnapshot,
) -> HeartbeatHealthPayload:
    """Build heartbeat payload from a lifecycle snapshot.

    Args:
        snapshot: See function signature.

    Returns:
        Return value.
    """
    return HeartbeatHealthPayload(
        heartbeat=HeartbeatDetailsPayload(
            app=app_check_from_status(snapshot.status),
            redis=dependency_check_from_status(snapshot.redis_status),
            database=dependency_check_from_status(snapshot.database_status),
            lifecycle=snapshot.status.value,
            draining=snapshot.draining,
            drain_reason=snapshot.drain_reason,
            started_at=snapshot.started_at.isoformat(),
            drain_started_at=(
                None
                if snapshot.drain_started_at is None
                else snapshot.drain_started_at.isoformat()
            ),
        )
    )


def _dependency_unavailable_reason(snapshot: LifecycleSnapshot) -> str | None:
    if snapshot.database_status is DependencyHealthStatus.UNAVAILABLE:
        return "database_unavailable"
    if snapshot.redis_status is DependencyHealthStatus.UNAVAILABLE:
        return "redis_unavailable"
    return None
