"""Redis consumer responses responsibilities."""

from __future__ import annotations

from app.operations.application.maintenance_job_queue import (
    MaintenanceQueueUnavailableError,
)
from app.shared.types.redis_types import RedisResponse


class MaintenanceConsumerResponseDecoder:
    """Decode strict maintenance transition and claim replies."""

    @staticmethod
    def transition_response(raw: RedisResponse) -> tuple[str, str]:
        """Decode the bounded two-field maintenance Lua transition response.

        Args:
            raw: Raw Redis response from the maintenance transition Lua script.

        Returns:
            Tuple of `(state, detail)` strings returned by the transition script.

        Raises:
            MaintenanceQueueUnavailableError: If the response shape or element types are invalid.
        """
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance transition returned an invalid response"
            )
        state = MaintenanceConsumerResponseDecoder.response_text(raw[0])
        detail = MaintenanceConsumerResponseDecoder.response_text(raw[1])
        return (state, detail)

    @staticmethod
    def autoclaim_next_cursor(raw: RedisResponse) -> str:
        """Decode the XAUTOCLAIM continuation ID for the next bounded page.

        Args:
            raw: Raw Redis response from `XAUTOCLAIM`.

        Returns:
            Continuation stream ID cursor string.

        Raises:
            MaintenanceQueueUnavailableError: If the autoclaim response shape or cursor is invalid.
        """
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance autoclaim returned an invalid response"
            )
        return MaintenanceConsumerResponseDecoder.response_text(raw[0])

    @staticmethod
    def response_text(value: RedisResponse) -> str:
        """Decode one Redis text response field.

        Args:
            value: Raw Redis scalar response field.

        Returns:
            Decoded UTF-8 string value.

        Raises:
            MaintenanceQueueUnavailableError: If the field is not valid UTF-8 bytes or string.
        """
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance response text is invalid"
                ) from exc
        if isinstance(value, str):
            return value
        raise MaintenanceQueueUnavailableError(
            "Redis maintenance response field is invalid"
        )
