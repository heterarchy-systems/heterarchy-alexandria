"""Known Redis hash fields with legacy conversion order."""

from __future__ import annotations

from app.operations.application.maintenance_job_queue import (
    MaintenanceQueueUnavailableError,
)
from app.operations.infrastructure.maintenance_codec.contracts import (
    MaintenanceDeadLetterFields,
    MaintenanceStatusFields,
)
from app.operations.infrastructure.maintenance_codec.scalars import RedisValueDecoder
from app.shared.types.redis_types import RedisResponse


class RedisMaintenanceFields:
    """Validate incoming values before selecting known Redis hash fields."""

    @staticmethod
    def status(raw: RedisResponse) -> MaintenanceStatusFields:
        """Normalize one Redis status hash response into known maintenance fields.

        Args:
            raw: Raw Redis hash response for one maintenance job status record.

        Returns:
            Normalized maintenance status field mapping.

        Raises:
            MaintenanceQueueUnavailableError: If the Redis reply is not a mapping.
        """
        if not isinstance(raw, dict):
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance status must be a mapping"
            )
        normalized: MaintenanceStatusFields = MaintenanceStatusFields()
        for raw_key, raw_value in raw.items():
            key = RedisValueDecoder.text(raw_key, "status key")
            value = RedisValueDecoder.text(raw_value, key)
            if key == "job_id":
                normalized["job_id"] = value
            elif key == "kind":
                normalized["kind"] = value
            elif key == "status":
                normalized["status"] = value
            elif key == "requested_by":
                normalized["requested_by"] = value
            elif key == "source_id":
                normalized["source_id"] = value
            elif key == "limit":
                normalized["limit"] = value
            elif key == "force":
                normalized["force"] = value
            elif key == "attempts":
                normalized["attempts"] = value
            elif key == "submitted_at":
                normalized["submitted_at"] = value
            elif key == "started_at":
                normalized["started_at"] = value
            elif key == "finished_at":
                normalized["finished_at"] = value
            elif key == "stream_id":
                normalized["stream_id"] = value
            elif key == "result_json":
                normalized["result_json"] = value
            elif key == "error_summary":
                normalized["error_summary"] = value
            elif key == "attempt_history_json":
                normalized["attempt_history_json"] = value
            elif key == "last_retry_reason":
                normalized["last_retry_reason"] = value
            elif key == "last_retry_at":
                normalized["last_retry_at"] = value
            elif key == "dlq_state":
                normalized["dlq_state"] = value
        return normalized

    @staticmethod
    def dead_letter(raw: RedisResponse) -> MaintenanceDeadLetterFields:
        """Normalize one dead-letter stream hash into known fields.

        Args:
            raw: Raw Redis hash response for one dead-letter entry.

        Returns:
            Normalized dead-letter field mapping.

        Raises:
            MaintenanceQueueUnavailableError: If the Redis reply is not a mapping.
        """
        if not isinstance(raw, dict):
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter entry must be a mapping"
            )
        normalized: MaintenanceDeadLetterFields = MaintenanceDeadLetterFields()
        for raw_key, raw_value in raw.items():
            key = RedisValueDecoder.text(raw_key, "dead-letter key")
            value = RedisValueDecoder.text(raw_value, key)
            if key == "job_id":
                normalized["job_id"] = value
            elif key == "kind":
                normalized["kind"] = value
            elif key == "attempts":
                normalized["attempts"] = value
            elif key == "failed_at":
                normalized["failed_at"] = value
            elif key == "error_summary":
                normalized["error_summary"] = value
            elif key == "source_stream_id":
                normalized["source_stream_id"] = value
            elif key == "lifecycle":
                normalized["lifecycle"] = value
            elif key == "attempt_history_json":
                normalized["attempt_history_json"] = value
        return normalized
