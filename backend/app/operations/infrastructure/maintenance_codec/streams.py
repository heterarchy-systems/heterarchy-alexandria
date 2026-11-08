"""Redis delivery, queue summary and dead-letter response decoding."""

from __future__ import annotations

from app.operations.application.maintenance_job_queue import (
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    MaintenanceDeadLetterEntry,
    MaintenanceJobRequest,
)
from app.operations.domain.event_enum.maintenance_job_enums import (
    MaintenanceJobKind,
)
from app.operations.infrastructure.maintenance_codec.contracts import (
    EnqueueScriptResult,
    RedisStreamDelivery,
)
from app.operations.infrastructure.maintenance_codec.fields import (
    RedisMaintenanceFields,
)
from app.operations.infrastructure.maintenance_codec.history import (
    MaintenanceAttemptHistoryCodec,
)
from app.operations.infrastructure.maintenance_codec.scalars import (
    RedisStatusValueDecoder,
    RedisValueDecoder,
)
from app.shared.types.redis_types import RedisResponse


class RedisMaintenanceStreamDecoder:
    """Decode enqueue replies, stream deliveries and queue summaries."""

    @staticmethod
    def decode_enqueue_result(raw: RedisResponse) -> EnqueueScriptResult:
        """Decode the three-value Lua enqueue response.

        Args:
            raw: Typed recursive Redis response returned by the enqueue script.

        Returns:
            Normalized enqueue state, identifier, and stream identifier.

        Raises:
            MaintenanceQueueUnavailableError: If the enqueue response does not
                contain exactly 3 elements.
        """
        values = RedisValueDecoder.sequence(raw, "enqueue response")
        if len(values) != 3:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance enqueue returned an invalid response"
            )
        return EnqueueScriptResult(
            state=RedisValueDecoder.text(values[0], "enqueue state"),
            value=RedisValueDecoder.text(values[1], "enqueue value"),
            stream_id=RedisValueDecoder.text(values[2], "enqueue stream id"),
        )

    @staticmethod
    def decode_pending_count(raw: RedisResponse) -> int:
        """Decode XPENDING summary output without retaining detail rows.

        Args:
            raw: Typed XPENDING summary response.

        Returns:
            Number of pending deliveries in the consumer group.
        """
        if isinstance(raw, dict):
            pending = raw.get("pending")
            if pending is None:
                pending = raw.get(b"pending")
            return RedisValueDecoder.integer(pending, "pending")
        values = RedisValueDecoder.sequence(raw, "pending summary")
        if not values:
            return 0
        return RedisValueDecoder.integer(values[0], "pending")

    @staticmethod
    def decode_consumer_count(raw: RedisResponse) -> int:
        """Decode XINFO CONSUMERS output by counting bounded records.

        Args:
            raw: Typed XINFO CONSUMERS response.

        Returns:
            Number of registered consumers.
        """
        return len(RedisValueDecoder.sequence(raw, "consumer info"))

    @staticmethod
    def decode_autoclaim_delivery(raw: RedisResponse) -> RedisStreamDelivery | None:
        """Decode the first XAUTOCLAIM entry, if present.

        Args:
            raw: Typed XAUTOCLAIM response.

        Returns:
            Decoded stream delivery, or None when no stale entry was claimed.
        """
        values = RedisValueDecoder.sequence(raw, "autoclaim response")
        if len(values) < 2:
            return None
        entries = RedisValueDecoder.sequence(values[1], "autoclaim entries")
        if not entries:
            return None
        return RedisMaintenanceStreamDecoder.delivery(entries[0])

    @staticmethod
    def decode_readgroup_delivery(raw: RedisResponse) -> RedisStreamDelivery | None:
        """Decode the first XREADGROUP entry, if present.

        Args:
            raw: Typed XREADGROUP response.

        Returns:
            Decoded stream delivery, or None when no new entry was read.
        """
        streams = RedisValueDecoder.sequence(raw, "readgroup response")
        if not streams:
            return None
        stream_record = RedisValueDecoder.sequence(streams[0], "readgroup stream")
        if len(stream_record) < 2:
            return None
        entries = RedisValueDecoder.sequence(stream_record[1], "readgroup entries")
        if not entries:
            return None
        return RedisMaintenanceStreamDecoder.delivery(entries[0])

    @staticmethod
    def delivery(raw: RedisResponse) -> RedisStreamDelivery:
        """Decode a two-element Redis stream entry into a delivery record.

        Args:
            raw: Raw Redis stream entry tuple containing stream id and field hash.

        Returns:
            Normalized RedisStreamDelivery with stream_id and job_id.

        Raises:
            MaintenanceQueueUnavailableError: If the stream entry is malformed.
        """
        values = RedisValueDecoder.sequence(raw, "stream delivery")
        if len(values) != 2:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance stream delivery is invalid"
            )
        fields = RedisMaintenanceFields.status(values[1])
        return RedisStreamDelivery(
            stream_id=RedisValueDecoder.text(values[0], "stream id"),
            job_id=RedisStatusValueDecoder.required(fields.get("job_id"), "job_id"),
        )


class RedisDeadLetterDecoder:
    """Decode terminal entries, source requests and transition replies."""

    @staticmethod
    def decode_dead_letter_entries(
        raw: RedisResponse,
    ) -> tuple[MaintenanceDeadLetterEntry, ...]:
        """Decode bounded XRANGE or XREVRANGE dead-letter stream output.

        Args:
            raw: Typed recursive Redis response holding stream entries.

        Returns:
            Immutable dead-letter entries in the order Redis returned them.

        Raises:
            MaintenanceQueueUnavailableError: If any dead-letter stream entry is
                malformed.
        """
        records = RedisValueDecoder.sequence(raw, "dead-letter entries")
        entries: list[MaintenanceDeadLetterEntry] = []
        for record in records:
            values = RedisValueDecoder.sequence(record, "dead-letter entry")
            if len(values) != 2:
                raise MaintenanceQueueUnavailableError(
                    "Redis dead-letter entry is invalid"
                )
            fields = RedisMaintenanceFields.dead_letter(values[1])
            entries.append(
                MaintenanceDeadLetterEntry(
                    entry_id=RedisValueDecoder.text(values[0], "dead-letter entry id"),
                    job_id=RedisStatusValueDecoder.required(
                        fields.get("job_id"), "job_id"
                    ),
                    kind=RedisStatusValueDecoder.parse_enum(
                        MaintenanceJobKind,
                        RedisStatusValueDecoder.required(fields.get("kind"), "kind"),
                        "kind",
                    ),
                    attempts=RedisValueDecoder.text_integer(
                        RedisStatusValueDecoder.required(
                            fields.get("attempts"), "attempts"
                        ),
                        "attempts",
                    ),
                    failed_at=RedisStatusValueDecoder.parse_datetime(
                        RedisStatusValueDecoder.required(
                            fields.get("failed_at"), "failed_at"
                        ),
                        "failed_at",
                    ),
                    error_summary=RedisStatusValueDecoder.nonblank(
                        fields.get("error_summary")
                    )
                    or "",
                    source_stream_id=RedisStatusValueDecoder.required(
                        fields.get("source_stream_id"), "source_stream_id"
                    ),
                    lifecycle=fields.get("lifecycle") or "ACTIVE",
                    attempt_history=MaintenanceAttemptHistoryCodec.decode_text(
                        fields.get("attempt_history_json")
                    ),
                )
            )
        return tuple(entries)

    @staticmethod
    def decode_dead_letter_source_request(
        raw: RedisResponse,
    ) -> MaintenanceJobRequest | None:
        """Decode the maintenance request behind one dead-letter source entry.

        Args:
            raw: Typed recursive Redis response from the source stream range read.

        Returns:
            Replayed job request, or None when the source entry was trimmed.

        Raises:
            MaintenanceQueueUnavailableError: If the source stream entry is
                malformed.
        """
        records = RedisValueDecoder.sequence(raw, "dead-letter source entries")
        if not records:
            return None
        values = RedisValueDecoder.sequence(records[0], "dead-letter source entry")
        if len(values) != 2:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter source entry is invalid"
            )
        fields = RedisMaintenanceFields.status(values[1])
        return MaintenanceJobRequest(
            kind=RedisStatusValueDecoder.parse_enum(
                MaintenanceJobKind,
                RedisStatusValueDecoder.required(fields.get("kind"), "kind"),
                "kind",
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
        )

    @staticmethod
    def decode_dead_letter_transition(raw: RedisResponse) -> tuple[str, str, str]:
        """Decode one bounded retry/reservation Lua transition response.

        Args:
            raw: Raw Redis sequence returned by the dead-letter transition script.

        Returns:
            Tuple of transition state, value, and optional detail text.

        Raises:
            MaintenanceQueueUnavailableError: If the reply does not have 2 or 3 elements.
        """
        values = RedisValueDecoder.sequence(raw, "dead-letter transition response")
        if len(values) not in {2, 3}:
            raise MaintenanceQueueUnavailableError(
                "Redis dead-letter transition response is invalid"
            )
        return (
            RedisValueDecoder.text(values[0], "dead-letter transition state"),
            RedisValueDecoder.text(values[1], "dead-letter transition value"),
            RedisValueDecoder.text(values[2], "dead-letter transition detail")
            if len(values) == 3
            else "",
        )
