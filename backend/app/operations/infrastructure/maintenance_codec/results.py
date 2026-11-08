"""Persisted batch-write and embedding result codecs."""

from __future__ import annotations

from collections.abc import Sequence

from app.operations.application.maintenance_job_queue import (
    MaintenanceQueueUnavailableError,
)
from app.operations.domain.entities.maintenance_job import (
    BatchNoteWriteJobItem,
    BatchNoteWriteJobResult,
    EmbeddingReindexJobResult,
)
from app.operations.domain.event_enum.maintenance_job_enums import MaintenanceJobKind
from app.operations.infrastructure.maintenance_codec.contracts import (
    BatchNoteWriteJobItemPayload,
    BatchNoteWriteJobResultPayload,
    EmbeddingReindexJobResultPayload,
)
from app.operations.infrastructure.maintenance_codec.scalars import (
    JsonResultValueDecoder,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue


class MaintenanceResultCodec:
    """Serialize and decode persisted results by their declared job kind."""

    @staticmethod
    def decode_job_result(
        kind: str | None, payload: bytes | str
    ) -> EmbeddingReindexJobResult | BatchNoteWriteJobResult:
        """Decode a persisted job result according to the job kind.

        Args:
            kind: Job kind recorded on the status hash.
            payload: Persisted JSON bytes or text from the Redis status hash.

        Returns:
            The kind-specific validated job result.

        Raises:
            MaintenanceQueueUnavailableError: When the kind is unknown.
        """
        if kind == MaintenanceJobKind.BATCH_NOTE_WRITE.value:
            return MaintenanceResultCodec.decode_batch_note_write_result(payload)
        if kind == MaintenanceJobKind.EMBEDDING_REINDEX.value:
            return MaintenanceResultCodec.decode_embedding_result(payload)
        raise MaintenanceQueueUnavailableError(
            "Redis maintenance job result kind is unknown"
        )

    @staticmethod
    def encode_batch_note_write_result(result: BatchNoteWriteJobResult) -> bytes:
        """Serialize a bounded batch note write result for the status hash.

        Args:
            result: Immutable batch note write result.

        Returns:
            UTF-8 JSON bytes encoded by the shared orjson boundary.
        """
        payload: JSONObject = dict[str, JSONValue](
            **BatchNoteWriteJobResultPayload(
                succeeded=result.succeeded,
                conflicted=result.conflicted,
                failed=result.failed,
                items=[
                    dict[str, JSONValue](
                        **BatchNoteWriteJobItemPayload(
                            path=item.path,
                            status=item.status,
                            content_hash=item.content_hash,
                            current_content_hash=item.current_content_hash,
                        )
                    )
                    for item in result.items
                ],
            )
        )
        return dumps_json(payload)

    @staticmethod
    def decode_batch_note_write_result(payload: bytes | str) -> BatchNoteWriteJobResult:
        """Validate and decode a persisted batch note write result.

        Args:
            payload: Persisted JSON bytes or text from the Redis status hash.

        Returns:
            Validated immutable batch note write result.

        Raises:
            MaintenanceQueueUnavailableError: If the persisted JSON structure or
                field types are invalid.
        """
        try:
            decoded = loads_json(payload)
        except ValueError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance result JSON is invalid"
            ) from exc
        if not isinstance(decoded, dict):
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance result JSON must be an object"
            )
        items_raw = decoded.get("items", [])
        if not isinstance(items_raw, Sequence) or isinstance(items_raw, str | bytes):
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance result items must be a sequence"
            )
        items: list[BatchNoteWriteJobItem] = []
        for item_raw in items_raw:
            if not isinstance(item_raw, dict):
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance result item must be an object"
                )
            items.append(
                BatchNoteWriteJobItem(
                    path=JsonResultValueDecoder.text(item_raw.get("path"), "path"),
                    status=JsonResultValueDecoder.text(
                        item_raw.get("status"), "status"
                    ),
                    content_hash=JsonResultValueDecoder.optional_text(
                        item_raw.get("content_hash")
                    ),
                    current_content_hash=JsonResultValueDecoder.optional_text(
                        item_raw.get("current_content_hash")
                    ),
                )
            )
        return BatchNoteWriteJobResult(
            succeeded=JsonResultValueDecoder.integer(
                decoded.get("succeeded"), "succeeded"
            ),
            conflicted=JsonResultValueDecoder.integer(
                decoded.get("conflicted"), "conflicted"
            ),
            failed=JsonResultValueDecoder.integer(decoded.get("failed"), "failed"),
            items=tuple(items),
        )

    @staticmethod
    def encode_embedding_result(result: EmbeddingReindexJobResult) -> bytes:
        """Serialize a bounded result with the shared orjson codec.

        Args:
            result: Immutable embedding reindex result.

        Returns:
            UTF-8 JSON bytes encoded by the shared orjson boundary.
        """
        payload: JSONObject = dict[str, JSONValue](
            **EmbeddingReindexJobResultPayload(
                scanned=result.scanned,
                updated=result.updated,
                skipped=result.skipped,
                warnings=list(result.warnings),
            )
        )
        return dumps_json(payload)

    @staticmethod
    def decode_embedding_result(payload: bytes | str) -> EmbeddingReindexJobResult:
        """Validate and decode a persisted embedding result.

        Args:
            payload: Persisted JSON bytes or text from the Redis status hash.

        Returns:
            Validated immutable embedding reindex result.

        Raises:
            MaintenanceQueueUnavailableError: If the persisted JSON structure or
                warning values are invalid.
        """
        try:
            decoded = loads_json(payload)
        except ValueError as exc:
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance result JSON is invalid"
            ) from exc
        if not isinstance(decoded, dict):
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance result JSON must be an object"
            )
        scanned = JsonResultValueDecoder.integer(decoded.get("scanned"), "scanned")
        updated = JsonResultValueDecoder.integer(decoded.get("updated"), "updated")
        skipped = JsonResultValueDecoder.integer(decoded.get("skipped"), "skipped")
        warnings_raw = decoded.get("warnings", [])
        if not isinstance(warnings_raw, Sequence) or isinstance(
            warnings_raw, str | bytes
        ):
            raise MaintenanceQueueUnavailableError(
                "Redis maintenance result warnings must be a sequence"
            )
        warnings: list[str] = []
        for warning in warnings_raw:
            if not isinstance(warning, str):
                raise MaintenanceQueueUnavailableError(
                    "Redis maintenance result warning must be text"
                )
            warnings.append(warning)
        return EmbeddingReindexJobResult(
            scanned=scanned, updated=updated, skipped=skipped, warnings=tuple(warnings)
        )

    @staticmethod
    def encode_result(
        result: EmbeddingReindexJobResult | BatchNoteWriteJobResult | None,
    ) -> bytes:
        """Return the canonical persisted result or an empty value for nonterminal work.

        Args:
            result: Optional terminal job result to serialize.

        Returns:
            Encoded UTF-8 JSON bytes, or empty bytes when result is None.
        """
        if isinstance(result, BatchNoteWriteJobResult):
            return MaintenanceResultCodec.encode_batch_note_write_result(result)
        if isinstance(result, EmbeddingReindexJobResult):
            return MaintenanceResultCodec.encode_embedding_result(result)
        return b""
