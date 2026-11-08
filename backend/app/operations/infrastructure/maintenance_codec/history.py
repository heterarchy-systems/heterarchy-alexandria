"""Bounded execution history serialization and validation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.operations.application.maintenance_job_queue import (
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceJobAttempt,
)
from app.operations.infrastructure.maintenance_codec.contracts import (
    MaintenanceJobAttemptPayload,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONValue


class MaintenanceAttemptHistoryCodec:
    """Validate complete attempt history before returning its bounded tail."""

    @staticmethod
    def encode_attempt_history(history: tuple[MaintenanceJobAttempt, ...]) -> bytes:
        """Serialize bounded execution history for Redis status evidence.

        Args:
            history: Ordered sequence of maintenance job attempts.

        Returns:
            UTF-8 JSON bytes encoding the most recent 20 attempt records.
        """
        return dumps_json(
            [
                dict[str, JSONValue](
                    **MaintenanceJobAttemptPayload(
                        attempt=item.attempt,
                        status=item.status,
                        occurred_at=item.occurred_at.isoformat(),
                        error_summary=item.error_summary,
                    )
                )
                for item in history[-20:]
            ]
        )

    @staticmethod
    def decode_attempt_history(
        payload: bytes | str | None,
    ) -> tuple[MaintenanceJobAttempt, ...]:
        """Decode bounded execution history from raw Redis bytes or text.

        Args:
            payload: Raw UTF-8 JSON bytes or string containing attempt history.

        Returns:
            Tuple of up to 20 validated MaintenanceJobAttempt records.

        Raises:
            MaintenanceQueueUnavailableError: If the payload is not valid UTF-8
                or valid attempt history JSON.
        """
        if payload is None:
            return ()
        if isinstance(payload, bytes):
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance attempt history is not valid UTF-8"
                ) from exc
        else:
            text = payload
        return MaintenanceAttemptHistoryCodec.decode_text(text)

    @staticmethod
    def decode_text(payload: str | None) -> tuple[MaintenanceJobAttempt, ...]:
        """Parse and validate bounded execution history from a JSON text string.

        Args:
            payload: Optional JSON string encoding a list of attempt objects.

        Returns:
            Tuple of up to 20 validated MaintenanceJobAttempt records.

        Raises:
            MaintenanceQueueUnavailableError: If the JSON structure or fields are invalid.
        """
        if not payload:
            return ()
        try:
            decoded = loads_json(payload)
        except ValueError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance attempt history JSON is invalid"
            ) from exc
        if not isinstance(decoded, Sequence) or isinstance(decoded, str | bytes):
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance attempt history must be a sequence"
            )
        history: list[MaintenanceJobAttempt] = []
        for item in decoded:
            if not isinstance(item, dict):
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance attempt history item must be an object"
                )
            occurred_at = item.get("occurred_at")
            if not isinstance(occurred_at, str):
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance attempt history timestamp is invalid"
                )
            try:
                parsed_at = datetime.fromisoformat(occurred_at)
            except ValueError as exc:
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance attempt history timestamp is invalid"
                ) from exc
            if parsed_at.tzinfo is None:
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance attempt history timestamp must be aware"
                )
            attempt = item.get("attempt")
            status = item.get("status")
            if (
                isinstance(attempt, bool)
                or not isinstance(attempt, int)
                or not isinstance(status, str)
                or (not status)
            ):
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance attempt history item is invalid"
                )
            error_summary = item.get("error_summary")
            if error_summary is not None and (not isinstance(error_summary, str)):
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance attempt history error is invalid"
                )
            history.append(
                MaintenanceJobAttempt(
                    attempt=attempt,
                    status=status,
                    occurred_at=parsed_at,
                    error_summary=error_summary,
                )
            )
        return tuple(history[-20:])
