"""Replay, checkpoint, owner-update, and identity support for report bundles."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from app.obsidian.application.notes.lifecycle.obsidian_canonical_note_path import (
    canonical_managed_note_path,
)
from app.obsidian.application.service.notes.report_bundles.obsidian_report_bundle_identity import (
    report_bundle_request_hash,
    same_report_content,
    same_report_identity,
)

if TYPE_CHECKING:
    from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianReportBundleOwner,
    ObsidianReportBundleRequest,
    ObsidianSaveNote,
    ObsidianVaultInventoryRequest,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianNoteWriteResult,
    ObsidianReportBundleGraphResult,
    ObsidianReportBundleResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianFrontmatterMode,
    ObsidianRelationType,
    ObsidianReportBundleCompletionStatus,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
    ObsidianWriteOperation,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)
from app.shared.types.extra_types import JSONObject, JSONValue


class ObsidianReportBundleSupport:
    """Provide deterministic non-orchestration support for report-bundle runs."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        vault_config_store: ObsidianVaultConfigStore,
    ) -> None:
        """Initialize report-bundle support dependencies.

        Args:
            obsidian_service: Stable canonical note facade.
            vault_config_store: Current managed-vault configuration.
        """
        self._obsidian_service = obsidian_service
        self._vault_config_store = vault_config_store

    @staticmethod
    def request_hash(request: ObsidianReportBundleRequest) -> str:
        """Return the canonical idempotency hash for one normalized request.

        Args:
            request: Canonicalized report-bundle request.

        Returns:
            Stable SHA-256 request hash used by durable replay checkpoints.
        """
        return report_bundle_request_hash(request)

    @staticmethod
    def operation_error(function: str, error: Exception) -> JSONObject:
        """Return one public-safe operation error payload.

        Args:
            function: Stable operation or stage name.
            error: Exception whose secret-safe message is reported.

        Returns:
            JSON object suitable for report-bundle failure evidence.
        """
        return _operation_error(function, error)

    def normalize_request(
        self,
        request: ObsidianReportBundleRequest,
    ) -> ObsidianReportBundleRequest:
        """Normalize a report bundle request.

        Args:
            request: Request to normalize or process.

        Returns:
            Normalized value.
        """
        root = self._vault_config_store.current().alexandria_root
        if request.source.relative_path is None:
            raise ObsidianValidationError("report bundle source.path is required")
        source = replace(
            request.source,
            relative_path=canonical_managed_note_path(
                request.source.relative_path,
                alexandria_root=root,
            ),
        )
        owners = tuple(
            replace(
                owner,
                path=canonical_managed_note_path(
                    owner.path,
                    alexandria_root=root,
                ),
            )
            for owner in request.graph_owners
        )
        if len({owner.path for owner in owners}) != len(owners):
            raise ObsidianValidationError("graph owner paths must be unique")
        return replace(request, source=source, graph_owners=owners)

    async def duplicate_paths(
        self,
        request: ObsidianReportBundleRequest,
        source: ObsidianNote,
    ) -> tuple[str, ...]:
        """Find exact content or declared report-identity duplicates.

        Args:
            request: Normalized bundle request defining the expected source path.
            source: Canonical source note written for the bundle.

        Returns:
            Sorted vault-relative paths of duplicate notes.
        """
        duplicates: set[str] = set()
        requested_path = request.source.relative_path
        if requested_path is not None and source.relative_path != requested_path:
            duplicates.add(source.relative_path)
        inventory = await self._obsidian_service.inventory_vault(
            ObsidianVaultInventoryRequest()
        )
        for item in inventory:
            if item.note_id == source.note_id:
                continue
            try:
                candidate = await self._obsidian_service.read_note(item.note_id)
            except ObsidianNotFoundError:
                continue
            if same_report_content(source, candidate) or same_report_identity(
                source,
                candidate,
            ):
                duplicates.add(candidate.relative_path)
        return tuple(sorted(duplicates))

    async def update_owner(
        self,
        contract: ObsidianReportBundleOwner,
        owner: ObsidianNote,
        source: ObsidianNoteWriteResult,
    ) -> ObsidianNoteWriteResult:
        """Update report bundle ownership metadata.

        Args:
            contract: Normalized report-bundle contract whose ownership is updated.
            owner: Owner metadata to persist on the report bundle.
            source: Source metadata associated with the operation.

        Returns:
            Write result produced by the owner metadata update.
        """
        field_name = _relation_field(contract.relation)
        targets = _relation_targets(owner.frontmatter.get(field_name))
        if not any(
            target.get("id") == source.note.note_id
            or target.get("path") == source.note.relative_path
            for target in targets
            if isinstance(target, dict)
        ):
            targets.append(
                {
                    "id": source.note.note_id,
                    "path": source.note.relative_path,
                    "relation": contract.relation.value,
                }
            )
        payload = ObsidianSaveNote(
            title=owner.title,
            body=owner.body.removeprefix("\n"),
            alexandria_type=owner.alexandria_type,
            note_id=owner.note_id,
            relative_path=owner.relative_path,
            tags=owner.tags,
            status=owner.status,
            project=owner.project,
            source=owner.source or "report_bundle",
            frontmatter={field_name: targets},
            expected_content_hash=owner.content_hash,
        )
        return await self._obsidian_service.write_note(
            ObsidianWriteNote(
                note=payload,
                write_mode=ObsidianWriteMode.UPDATE,
                match_by=ObsidianWriteMatchBy.PATH,
                frontmatter_mode=ObsidianFrontmatterMode.MERGE,
            )
        )

    async def completed_replay(
        self,
        request: ObsidianReportBundleRequest,
        checkpoint: JSONObject | None,
    ) -> ObsidianReportBundleResult | None:
        """Build a completed replay result.

        Args:
            request: Request to normalize or process.
            checkpoint: Previously persisted report-bundle checkpoint.

        Returns:
            Completed replay result when a reusable checkpoint exists; otherwise None.
        """
        if checkpoint is None or checkpoint.get("completion_status") not in {
            ObsidianReportBundleCompletionStatus.COMPLETED.value,
            ObsidianReportBundleCompletionStatus.COMPLETED_WITH_WARNINGS.value,
        }:
            return None
        source_note_id = checkpoint.get("source_note_id")
        if not isinstance(source_note_id, str):
            return None
        try:
            note = await self._obsidian_service.read_note(source_note_id)
        except ObsidianNotFoundError:
            return None
        expected = _checkpoint_int(checkpoint, "expected_incoming_edges")
        verified = _checkpoint_int(checkpoint, "verified_incoming_edges")
        owner_writes: list[ObsidianNoteWriteResult] = []
        for owner_record in _checkpoint_dicts(checkpoint, "owner_writes"):
            note_id = owner_record.get("note_id")
            operation = owner_record.get("operation")
            if not isinstance(note_id, str) or not isinstance(operation, str):
                continue
            try:
                owner_note = await self._obsidian_service.read_note(note_id)
            except ObsidianNotFoundError:
                continue
            owner_writes.append(
                ObsidianNoteWriteResult(
                    operation=ObsidianWriteOperation(operation),
                    write_mode=ObsidianWriteMode.UPDATE,
                    match_by=ObsidianWriteMatchBy.PATH,
                    note=owner_note,
                    storage_status="unchanged",
                    metadata_status="indexed",
                    fts_status="indexed",
                    graph_edge_index_status="indexed",
                    graph_projection_status="ready",
                    reindex_required=False,
                )
            )
        source = ObsidianNoteWriteResult(
            operation=ObsidianWriteOperation.UNCHANGED,
            write_mode=ObsidianWriteMode.UPSERT,
            match_by=ObsidianWriteMatchBy.PATH,
            note=note,
            storage_status="unchanged",
            metadata_status="indexed",
            fts_status="indexed",
            graph_edge_index_status="indexed",
            graph_projection_status="ready",
            reindex_required=False,
        )
        return ObsidianReportBundleResult(
            completion_status=ObsidianReportBundleCompletionStatus(
                str(checkpoint["completion_status"])
            ),
            idempotency_key=request.idempotency_key,
            replayed=True,
            source=source,
            owner_writes=tuple(owner_writes),
            graph=ObsidianReportBundleGraphResult(
                expected_incoming_edges=expected,
                verified_incoming_edges=verified,
                unresolved_links=tuple(
                    _checkpoint_strings(checkpoint, "unresolved_links")
                ),
            ),
            duplicates=tuple(_checkpoint_strings(checkpoint, "duplicates")),
            failed_stage=_checkpoint_string(checkpoint, "failed_stage"),
            errors=tuple(_checkpoint_dicts(checkpoint, "errors")),
        )

    @staticmethod
    def failure(
        request: ObsidianReportBundleRequest,
        status: ObsidianReportBundleCompletionStatus,
        stage: str,
        error: Exception,
        source: ObsidianNoteWriteResult | None = None,
        owner_writes: tuple[ObsidianNoteWriteResult, ...] = (),
    ) -> ObsidianReportBundleResult:
        """Build a report bundle failure result.

        Args:
            request: Request to normalize or process.
            status: Current operation or report status.
            stage: Report-bundle stage at which the failure occurred.
            error: Error details captured for the response or report.
            source: Source metadata associated with the operation.
            owner_writes: Write results produced while persisting owner notes.

        Returns:
            Failure result describing the report-bundle stage and error.
        """
        return ObsidianReportBundleResult(
            completion_status=status,
            idempotency_key=request.idempotency_key,
            replayed=False,
            source=source,
            owner_writes=owner_writes,
            graph=ObsidianReportBundleGraphResult(
                expected_incoming_edges=len(request.graph_owners),
                verified_incoming_edges=0,
            ),
            failed_stage=stage,
            errors=(_operation_error(stage.lower(), error),),
        )

    @staticmethod
    def save_checkpoint(
        store: ObsidianReportBundleRunStore,
        request: ObsidianReportBundleRequest,
        request_hash: str,
        result: ObsidianReportBundleResult,
    ) -> None:
        """Persist a report bundle checkpoint.

        Args:
            store: Checkpoint store used to persist report-bundle progress.
            request: Request to normalize or process.
            request_hash: Stable request hash used for checkpoint idempotency.
            result: Operation result to serialize or persist.
        """
        store.save(
            request.idempotency_key,
            {
                "request_hash": request_hash,
                "completion_status": result.completion_status.value,
                "failed_stage": result.failed_stage,
                "source_note_id": (
                    None if result.source is None else result.source.note.note_id
                ),
                "expected_incoming_edges": result.graph.expected_incoming_edges,
                "verified_incoming_edges": result.graph.verified_incoming_edges,
                "unresolved_links": list(result.graph.unresolved_links),
                "duplicates": list(result.duplicates),
                "errors": list(result.errors),
                "owner_writes": [
                    {
                        "note_id": item.note.note_id,
                        "operation": item.operation.value,
                    }
                    for item in result.owner_writes
                ],
            },
        )


def _relation_field(relation: ObsidianRelationType) -> str:
    """Execute relation field.

    Args:
        relation: Relation used by this operation.

    Returns:
        str result produced by relation field.
    """
    if relation is ObsidianRelationType.CITES:
        return "source_ref_links"
    if relation is ObsidianRelationType.WIKILINK:
        raise ObsidianValidationError(
            "graph owner relation must be a managed frontmatter relation"
        )
    return relation.value


def _relation_targets(value: JSONValue | None) -> list[JSONValue]:
    """Execute relation targets.

    Args:
        value: Value being processed.

    Returns:
        list[JSONValue] result produced by relation targets.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _operation_error(function: str, error: Exception) -> JSONObject:
    """Execute operation error.

    Args:
        function: Function used by this operation.
        error: Error value being processed.

    Returns:
        JSONObject result produced by operation error.
    """
    return {"function": function, "message": str(error) or type(error).__name__}


def _checkpoint_int(checkpoint: JSONObject, key: str) -> int:
    """Execute checkpoint int.

    Args:
        checkpoint: Checkpoint used by this operation.
        key: Key used by this operation.

    Returns:
        int result produced by checkpoint int.
    """
    value = checkpoint.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _checkpoint_string(checkpoint: JSONObject, key: str) -> str | None:
    """Execute checkpoint string.

    Args:
        checkpoint: Checkpoint used by this operation.
        key: Key used by this operation.

    Returns:
        str | None result produced by checkpoint string.
    """
    value = checkpoint.get(key)
    return value if isinstance(value, str) else None


def _checkpoint_strings(checkpoint: JSONObject, key: str) -> list[str]:
    """Execute checkpoint strings.

    Args:
        checkpoint: Checkpoint used by this operation.
        key: Key used by this operation.

    Returns:
        list[str] result produced by checkpoint strings.
    """
    value = checkpoint.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _checkpoint_dicts(checkpoint: JSONObject, key: str) -> list[JSONObject]:
    """Execute checkpoint dicts.

    Args:
        checkpoint: Checkpoint used by this operation.
        key: Key used by this operation.

    Returns:
        list[JSONObject] result produced by checkpoint dicts.
    """
    value = checkpoint.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
