"""Rebuild the Obsidian vault index from canonical Markdown sources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from typing_extensions import TypedDict as ClosedTypedDict

from app.obsidian.application.notes.lifecycle.obsidian_context_reindex_manifest import (
    ContextReindexCandidate,
    supersedes_context_id,
)
from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.application.vault.compile_inputs import VaultCompileInputMapper
from app.obsidian.application.vault.index_errors import VaultIndexDiagnostics
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianReindexResult,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.markdown.paths import (
    canonical_relative_path,
    discover_managed_markdown_paths,
    validate_discovered_note_path,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfig,
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIndexWriteError,
    ObsidianValidationError,
)
from app.shared.infrastructure.critical_task import run_critical_sync
from app.shared.infrastructure.native_compute.native_compile_plan import (
    CompilePlanResult,
    create_native_compile_plan_provider,
)
from app.shared.types.types_convert_utils import now_utc

if TYPE_CHECKING:
    from app.obsidian.application.vault.vault_lifecycle_service import (
        ObsidianMarkSupersededHook,
    )


class CompileReceiptPayload(ClosedTypedDict, closed=True):
    """Durable evidence written after one successful compile-plan application."""

    plan_fingerprint: str
    policy_version: str
    applied_at: str
    changed_documents: int
    removed_documents: int
    embedding_invalidated_documents: int
    diagnostic_count: int


@dataclass(slots=True)
class _ReindexDiagnostics:
    """Mutable accumulator for per-note errors collected during one reindex run."""

    errors: list[str] = field(default_factory=list)
    details: list[ObsidianIndexError] = field(default_factory=list)


class VaultReindexExecutor:
    """Run one serialized vault index rebuild using borrowed runtime authorities."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_config_store: ObsidianVaultConfigStore,
        note_id_from_existing_file: Callable[[Path], str | None],
        mark_context_superseded: ObsidianMarkSupersededHook,
        context_reindex_hook: Callable[[Sequence[str] | None], Awaitable[None]] | None,
        embedding_fingerprint_key: str | None,
        root_path: Callable[[ObsidianVaultConfig], Path],
    ) -> None:
        """Bind the existing repositories, hooks, and pure compile mapper.

        Args:
            repository: Rebuildable PostgreSQL index repository.
            vault_config_store: Runtime vault location provider.
            note_id_from_existing_file: Safe frontmatter identifier reader.
            mark_context_superseded: Context lifecycle reconciliation callback.
            context_reindex_hook: Optional Context RAG reindex callback.
            embedding_fingerprint_key: Active native compile embedding identity.
            root_path: Existing managed-root resolver owned by the lifecycle service.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._note_id_from_existing_file = note_id_from_existing_file
        self._mark_context_superseded = mark_context_superseded
        self._context_reindex_hook = context_reindex_hook
        self._embedding_fingerprint_key = embedding_fingerprint_key
        self._root_path = root_path
        self._compile_inputs = VaultCompileInputMapper()
        self._index_diagnostics = VaultIndexDiagnostics(repository)

    async def run(self) -> ObsidianReindexResult:
        """Run one vault scan while the shared maintenance lease is held.

        Returns:
            Reindex summary with counts and warnings.
        """
        config = self._vault_config_store.current()
        root = self._root_path(config)
        if not root.exists():
            indexed = await self._repository.list_indexed_note_identifiers()
            return ObsidianReindexResult(
                files_seen=0,
                files_indexed=0,
                files_skipped=0,
                stale_marked=await self._repository.mark_documents_stale(
                    tuple(path for _, path in indexed)
                ),
                errors=("Alexandria Obsidian root does not exist",),
            )
        files_seen = 0
        files_skipped = 0
        skip_reasons: dict[str, int] = {}
        diagnostics = _ReindexDiagnostics()
        seen_paths: set[str] = set()
        candidates: list[ContextReindexCandidate] = []
        discovered_paths = discover_managed_markdown_paths(root)
        paths_by_logical_identity: dict[str, list[Path]] = {}
        for path in discovered_paths:
            physical_relative_path = str(path.relative_to(config.vault_path))
            logical_relative_path = canonical_relative_path(physical_relative_path)
            paths_by_logical_identity.setdefault(logical_relative_path, []).append(path)
        colliding_paths = {
            relative_path
            for relative_path, physical_paths in paths_by_logical_identity.items()
            if len(physical_paths) > 1
        }
        for path in discovered_paths:
            files_seen += 1
            relative_path = str(path.relative_to(config.vault_path))
            logical_relative_path = canonical_relative_path(relative_path)
            if logical_relative_path in colliding_paths:
                await self._index_diagnostics.record(
                    relative_path,
                    self._note_id_from_existing_file(path),
                    ObsidianValidationError(
                        "CANONICAL_PATH_COLLISION: multiple physical Markdown "
                        f"paths normalize to {relative_path}"
                    ),
                    diagnostics.errors,
                    diagnostics.details,
                )
                continue
            seen_paths.add(relative_path)
            try:
                validated_path = validate_discovered_note_path(
                    config.vault_path,
                    config.alexandria_root,
                    path,
                )
                payload = note_index_from_path(
                    validated_path,
                    relative_path,
                    alexandria_root=config.alexandria_root,
                )
                if payload is None:
                    await self._repository.clear_index_error(relative_path)
                    files_skipped += 1
                    skip_reasons["missing_alexandria_frontmatter"] = (
                        skip_reasons.get("missing_alexandria_frontmatter", 0) + 1
                    )
                    continue
                candidates.append(
                    ContextReindexCandidate(path=validated_path, payload=payload)
                )
            except (
                OSError,
                ValueError,
                ObsidianIndexWriteError,
                ObsidianValidationError,
            ) as exc:
                await self._index_diagnostics.record(
                    relative_path,
                    self._note_id_from_existing_file(path),
                    exc,
                    diagnostics.errors,
                    diagnostics.details,
                )
        previous_states = await self._repository.list_compiled_document_states()
        current_embedding_fingerprint_key = (
            self._embedding_fingerprint_key or "__embedding_disabled__"
        )
        previous_embedding_fingerprint_key = (
            current_embedding_fingerprint_key
            if self._embedding_fingerprint_key is None
            else (
                await self._repository.read_compiled_embedding_fingerprint_key()
                or "__embedding_incomplete__"
            )
        )
        policy = self._compile_inputs.policy(current_embedding_fingerprint_key)
        current_documents = [
            self._compile_inputs.document(candidate) for candidate in candidates
        ]
        compile_provider = create_native_compile_plan_provider()
        previous_snapshot = self._compile_inputs.previous_snapshot(
            previous_states,
            previous_embedding_fingerprint_key,
        )
        plan: CompilePlanResult = compile_provider.compile(
            policy=policy,
            current_documents=current_documents,
            previous=previous_snapshot,
        )
        for diagnostic in plan["diagnostics"]:
            await self._index_diagnostics.record(
                diagnostic["relative_path"],
                diagnostic["context_id"],
                ValueError(diagnostic["message"]),
                diagnostics.errors,
                diagnostics.details,
            )
        payload_by_path = {
            candidate.payload.relative_path: candidate for candidate in candidates
        }
        resolved_targets: dict[str, dict[str, str]] = {}
        indexed_candidates: list[ContextReindexCandidate] = []
        for upsert in plan["upserts"]:
            relative_path = upsert["relative_path"]
            candidate = payload_by_path.get(relative_path)
            if (
                candidate is None
                or upsert["action"] == "EMBEDDING_ONLY"
                or not upsert["manifest_accepted"]
            ):
                continue
            edge_targets = {
                edge["edge_id"]: edge["target_note_id"]
                for edge in upsert["edges"]
                if edge["resolution"] == "RESOLVED" and edge["target_note_id"]
            }
            resolved_targets[relative_path] = edge_targets
            payload = replace(
                candidate.payload,
                edges=tuple(
                    replace(
                        edge,
                        target_note_id=edge_targets.get(edge.edge_id)
                        or edge.target_note_id,
                    )
                    for edge in candidate.payload.edges
                ),
            )
            reconciled_candidate = replace(candidate, payload=payload)
            try:
                await self._repository.upsert_note(reconciled_candidate.payload)
                indexed_candidates.append(reconciled_candidate)
            except ObsidianIndexWriteError as exc:
                await self._index_diagnostics.record(
                    relative_path,
                    candidate.payload.note_id,
                    exc,
                    diagnostics.errors,
                    diagnostics.details,
                )
        successfully_reconciled: list[ContextReindexCandidate] = []
        for candidate in indexed_candidates:
            superseded_context_id = supersedes_context_id(candidate.payload)
            if superseded_context_id is None:
                successfully_reconciled.append(candidate)
                continue
            try:
                await self._mark_context_superseded(
                    superseded_context_id=superseded_context_id,
                    replacement_context_id=candidate.payload.note_id,
                )
                successfully_reconciled.append(candidate)
            except (OSError, ObsidianValidationError) as exc:
                await self._index_diagnostics.record(
                    candidate.payload.relative_path,
                    candidate.payload.note_id,
                    exc,
                    diagnostics.errors,
                    diagnostics.details,
                )
        stale_marked = await self._repository.mark_documents_stale(
            tuple(
                removal["relative_path"]
                for removal in plan["removals"]
                if removal["relative_path"] not in seen_paths
            )
        )
        edge_targets_resolved = sum(
            len(targets) for targets in resolved_targets.values()
        )
        embedding_invalidated_documents = sum(
            1
            for upsert in plan["upserts"]
            if upsert["embedding"]["action"] == "REEMBED"
        )
        plan_fingerprint = plan["plan_fingerprint"]
        policy_version = plan["policy_version"]
        diagnostic_count = len(plan["diagnostics"])
        if self._context_reindex_hook is not None:
            invalidated_note_ids = tuple(
                upsert["note_id"]
                for upsert in plan["upserts"]
                if upsert["embedding"]["action"] == "REEMBED"
            )
            await self._context_reindex_hook(invalidated_note_ids or None)
        receipt = CompileReceiptPayload(
            plan_fingerprint=plan_fingerprint,
            policy_version=policy_version,
            applied_at=now_utc().isoformat(),
            changed_documents=len(plan["upserts"]),
            removed_documents=len(plan["removals"]),
            embedding_invalidated_documents=embedding_invalidated_documents,
            diagnostic_count=diagnostic_count,
        )
        await save_compile_receipt(config.vault_path, receipt)
        return ObsidianReindexResult(
            files_seen=files_seen,
            files_indexed=len(successfully_reconciled),
            files_skipped=files_skipped,
            stale_marked=stale_marked,
            errors=tuple(diagnostics.errors),
            error_details=tuple(diagnostics.details),
            skip_reasons=skip_reasons,
            edge_targets_resolved=edge_targets_resolved,
            plan_fingerprint=plan_fingerprint,
            policy_version=policy_version,
            embedding_invalidated_documents=embedding_invalidated_documents,
            diagnostic_count=diagnostic_count,
        )


async def save_compile_receipt(
    vault_path: Path,
    receipt: CompileReceiptPayload,
) -> None:
    """Persist one compile receipt through the owned blocking-work boundary.

    Args:
        vault_path: Active Obsidian vault root.
        receipt: Typed native compile result summary.
    """
    store = ObsidianReportBundleRunStore(vault_path=vault_path)
    await run_critical_sync(partial(store.save, "compile-receipt:latest", receipt))
