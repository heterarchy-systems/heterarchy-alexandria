"""Immutable maintenance job snapshots from Redis hashes."""

from __future__ import annotations

from app.operations.domain.entities.maintenance_job import (
    MaintenanceJobSnapshot,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
    MaintenanceJobStatus,
)
from app.operations.infrastructure.maintenance_codec.fields import (
    RedisMaintenanceFields,
)
from app.operations.infrastructure.maintenance_codec.history import (
    MaintenanceAttemptHistoryCodec,
)
from app.operations.infrastructure.maintenance_codec.results import (
    MaintenanceResultCodec,
)
from app.operations.infrastructure.maintenance_codec.scalars import (
    RedisStatusValueDecoder,
    RedisValueDecoder,
)
from app.shared.types.redis_types import RedisResponse


class MaintenanceSnapshotDecoder:
    """Decode status, attempt history and results into a job snapshot."""

    @staticmethod
    def decode_job_snapshot(raw: RedisResponse) -> MaintenanceJobSnapshot | None:
        """Decode one Redis status hash into an immutable domain snapshot.

        Args:
            raw: Typed Redis hash response loaded for one maintenance job.

        Returns:
            Immutable job snapshot, or None when the Redis hash is empty.

        Raises:
            MaintenanceQueueUnavailableError: If the Redis status hash or any of
                its required fields, enums, or JSON payloads are malformed.
        """
        fields = RedisMaintenanceFields.status(raw)
        if not fields:
            return None
        result_json = fields.get("result_json", "")
        return MaintenanceJobSnapshot(
            job_id=RedisStatusValueDecoder.required(fields.get("job_id"), "job_id"),
            kind=RedisStatusValueDecoder.parse_enum(
                MaintenanceJobKind,
                RedisStatusValueDecoder.required(fields.get("kind"), "kind"),
                "kind",
            ),
            status=RedisStatusValueDecoder.parse_enum(
                MaintenanceJobStatus,
                RedisStatusValueDecoder.required(fields.get("status"), "status"),
                "status",
            ),
            requested_by=RedisStatusValueDecoder.required(
                fields.get("requested_by"), "requested_by"
            ),
            source_id=RedisStatusValueDecoder.required(
                fields.get("source_id"), "source_id"
            ),
            limit=RedisValueDecoder.text_integer(
                RedisStatusValueDecoder.required(fields.get("limit"), "limit"), "limit"
            ),
            force=RedisStatusValueDecoder.required(fields.get("force"), "force") == "1",
            attempts=RedisValueDecoder.text_integer(
                RedisStatusValueDecoder.required(fields.get("attempts"), "attempts"),
                "attempts",
            ),
            submitted_at=RedisStatusValueDecoder.parse_datetime(
                RedisStatusValueDecoder.required(
                    fields.get("submitted_at"), "submitted_at"
                ),
                "submitted_at",
            ),
            started_at=RedisStatusValueDecoder.optional_datetime(
                fields.get("started_at"), "started_at"
            ),
            finished_at=RedisStatusValueDecoder.optional_datetime(
                fields.get("finished_at"), "finished_at"
            ),
            stream_id=RedisStatusValueDecoder.nonblank(fields.get("stream_id")),
            error_summary=RedisStatusValueDecoder.nonblank(fields.get("error_summary")),
            attempt_history=MaintenanceAttemptHistoryCodec.decode_text(
                fields.get("attempt_history_json")
            ),
            result=MaintenanceResultCodec.decode_job_result(
                fields.get("kind"), result_json
            )
            if result_json
            else None,
        )
