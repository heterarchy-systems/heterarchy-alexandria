"""Bounded batch note operations composing existing authoritative primitives."""

from __future__ import annotations

from collections.abc import Sequence

from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_service import (
    ObsidianGraphNoteDiagnosticsService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_batch_contracts import (
    BatchReadItemResult,
    BatchReadResult,
    BatchReadSelector,
    BatchValidateItemResult,
    BatchValidateResult,
    BatchWriteItemResult,
    BatchWriteOperation,
    BatchWriteResult,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianFrontmatterMode,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)

_MAX_OPERATIONS = 50


class ObsidianBatchNoteService:
    """Run bounded batch reads, link validations, and CAS writes.

    Every item is independent: one item's failure never fails the batch, and
    each result is reported item-level. Writes reuse the per-item CAS
    semantics of the authoritative write path (expected_content_hash), so a
    conflict only skips that one item. Default mode is independent; a single
    all-or-nothing transaction is intentionally not provided.
    """

    def __init__(
        self,
        obsidian_service: ObsidianService,
        diagnostics_service: ObsidianGraphNoteDiagnosticsService,
        max_operations: int = _MAX_OPERATIONS,
    ) -> None:
        """Create the batch note service.

        Args:
            obsidian_service: Authoritative note read/write facade.
            diagnostics_service: Per-note graph diagnostics service.
            max_operations: Upper bound on batch size.
        """
        if max_operations <= 0:
            raise ValueError("max_operations must be greater than zero")
        self._obsidian_service = obsidian_service
        self._diagnostics_service = diagnostics_service
        self._max_operations = max_operations

    async def batch_read(
        self,
        selectors: Sequence[BatchReadSelector],
    ) -> BatchReadResult:
        """Read many notes independently, reporting per-item status.

        Args:
            selectors: Exact note selectors (path or note_id each).

        Returns:
            Per-item read results in selector order.

        Raises:
            BatchValidationError: When the batch exceeds the size bound.
        """
        if len(selectors) > self._max_operations:
            raise _too_many(len(selectors), self._max_operations)
        items = [await self._read_one(selector) for selector in selectors]
        return BatchReadResult(items=tuple(items))

    async def batch_validate_links(
        self,
        selectors: Sequence[BatchReadSelector],
    ) -> BatchValidateResult:
        """Validate outgoing links for many notes independently.

        Args:
            selectors: Exact note selectors (path or note_id each).

        Returns:
            Per-item validation results in selector order.

        Raises:
            BatchValidationError: When the batch exceeds the size bound.
        """
        if len(selectors) > self._max_operations:
            raise _too_many(len(selectors), self._max_operations)
        items = [await self._validate_one(selector) for selector in selectors]
        return BatchValidateResult(items=tuple(items))

    async def batch_write(
        self,
        operations: Sequence[BatchWriteOperation],
    ) -> BatchWriteResult:
        """Execute many independent CAS writes, reporting per-item status.

        Args:
            operations: Write operations executed in request order.

        Returns:
            Per-item write results in request order.

        Raises:
            BatchValidationError: When the batch exceeds the size bound.
        """
        if len(operations) > self._max_operations:
            raise _too_many(len(operations), self._max_operations)
        items = [await self._write_one(operation) for operation in operations]
        return BatchWriteResult(items=tuple(items))

    async def _read_one(self, selector: BatchReadSelector) -> BatchReadItemResult:
        """Read one selector into an item result.

        Args:
            selector: Selector for this item.

        Returns:
            Item result with the note when found.
        """
        try:
            if selector.note_id is not None:
                note = await self._obsidian_service.read_note(selector.note_id)
            else:
                note = await self._obsidian_service.read_note_by_path(
                    selector.path or ""
                )
        except ObsidianNotFoundError:
            return BatchReadItemResult(
                path=selector.path,
                note_id=selector.note_id,
                status="not_found",
            )
        except ObsidianValidationError as exc:
            return BatchReadItemResult(
                path=selector.path,
                note_id=selector.note_id,
                status="parse_error",
                parse_error=str(exc),
            )
        except ValueError as exc:
            return BatchReadItemResult(
                path=selector.path,
                note_id=selector.note_id,
                status="parse_error",
                parse_error=str(exc),
            )
        return BatchReadItemResult(
            path=selector.path,
            note_id=selector.note_id,
            status="success",
            note=note,
        )

    async def _validate_one(
        self,
        selector: BatchReadSelector,
    ) -> BatchValidateItemResult:
        """Validate one selector's outgoing links via the diagnostics service.

        Args:
            selector: Selector for this item.

        Returns:
            Validation item result, or an invalid/not_found outcome.
        """
        try:
            report = await self._diagnostics_service.validate_note_links(
                note_id=selector.note_id,
                path=selector.path,
            )
        except ObsidianNotFoundError:
            return BatchValidateItemResult(
                path=selector.path,
                note_id=selector.note_id,
                status="not_found",
            )
        except ObsidianValidationError as exc:
            return BatchValidateItemResult(
                path=selector.path,
                note_id=selector.note_id,
                status="parse_error",
                error=str(exc),
            )
        return BatchValidateItemResult(
            path=selector.path or report.note.relative_path,
            note_id=selector.note_id,
            status="validated" if report.note.exists else "not_found",
            exists=report.note.exists,
            parsed_count=report.outgoing.parsed_count,
            resolved_count=report.outgoing.resolved_count,
            unresolved_count=report.outgoing.unresolved_count,
        )

    async def _write_one(
        self,
        operation: BatchWriteOperation,
    ) -> BatchWriteItemResult:
        """Execute one CAS write and classify the outcome.

        Args:
            operation: Write operation.

        Returns:
            Item result with status and content hash when written.
        """
        try:
            command = ObsidianWriteNote(
                note=ObsidianSaveNote(
                    title=operation.title,
                    body=operation.body,
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id=operation.note_id,
                    relative_path=operation.relative_path,
                    frontmatter=dict(operation.frontmatter),
                    expected_content_hash=operation.expected_content_hash,
                ),
                write_mode=ObsidianWriteMode.UPSERT,
                match_by=ObsidianWriteMatchBy.PATH,
                frontmatter_mode=ObsidianFrontmatterMode.MERGE,
            )
            result = await self._obsidian_service.write_note(command)
        except ObsidianWriteConflictError as exc:
            return BatchWriteItemResult(
                path=operation.relative_path,
                note_id=operation.note_id,
                status="conflict",
                current_content_hash=exc.current_content_hash,
            )
        except ObsidianNotFoundError:
            return BatchWriteItemResult(
                path=operation.relative_path,
                note_id=operation.note_id,
                status="not_found",
            )
        except ValueError:
            return BatchWriteItemResult(
                path=operation.relative_path,
                note_id=operation.note_id,
                status="invalid",
            )
        if result.operation.value == "UNCHANGED":
            return BatchWriteItemResult(
                path=operation.relative_path,
                note_id=operation.note_id,
                status="unchanged",
                content_hash=result.note.content_hash,
            )
        return BatchWriteItemResult(
            path=operation.relative_path,
            note_id=operation.note_id,
            status=result.operation.value.lower(),
            content_hash=result.note.content_hash,
        )


def _too_many(actual: int, maximum: int) -> Exception:
    """Build the batch size exceeded error.

    Args:
        actual: Requested batch size.
        maximum: Allowed batch size.

    Returns:
        Batch validation error.
    """
    from app.obsidian.domain.contracts.obsidian_batch_contracts import (
        BatchValidationError,
    )

    return BatchValidationError(
        f"BATCH_SIZE_EXCEEDED: {actual} operations exceeds the {maximum} limit"
    )
