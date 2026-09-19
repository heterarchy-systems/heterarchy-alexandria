"""Obsidian vault configuration, initialization, and indexing lifecycle."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from app.obsidian.application.notes.lifecycle.obsidian_context_reindex_manifest import (
    ContextReindexCandidate,
    manifest_frontmatter_text,
    supersedes_context_id,
)
from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.application.notes.obsidian_note_templates import (
    default_folders,
    start_here_body,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianVaultSettingsUpdate,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianNote,
    ObsidianReindexResult,
    ObsidianVaultStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexErrorCode,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.markdown.paths import (
    canonical_relative_path,
    discover_managed_markdown_paths,
    resolve_note_path,
    validate_discovered_note_path,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfig,
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIndexWriteError,
    ObsidianValidationError,
)
from app.shared.infrastructure.native_compile_plan import (
    CompileDocumentWire,
    create_native_compile_plan_provider,
)
from app.shared.search.markdown_text_chunking import (
    DEFAULT_SEARCH_CHUNK_MAX_CHARS,
    DEFAULT_SEARCH_CHUNK_OVERLAP_CHARS,
)
from app.shared.types.extra_types import JSONObject
from app.shared.types.types_convert_utils import now_utc


@dataclass(slots=True)
class _ReindexDiagnostics:
    """Mutable accumulator for per-note errors collected during one reindex run."""

    errors: list[str] = field(default_factory=list)
    details: list[ObsidianIndexError] = field(default_factory=list)


# protocol-contract: structural-seam
class ObsidianLifecycleReadHook(Protocol):
    """Read one note by vault-relative path."""

    async def __call__(self, relative_path: str) -> ObsidianNote:
        """Read one note.

        Args:
            relative_path: Vault-relative note path.

        Returns:
            Canonical indexed note.
        """


# protocol-contract: structural-seam
class ObsidianLifecycleSaveHook(Protocol):
    """Persist one note through the canonical save path."""

    async def __call__(self, payload: ObsidianSaveNote) -> ObsidianNote:
        """Save one note.

        Args:
            payload: Canonical save command.

        Returns:
            Persisted and indexed note.
        """


# protocol-contract: structural-seam
class ObsidianMarkSupersededHook(Protocol):
    """Reconcile a superseded Context during reindex."""

    async def __call__(
        self,
        superseded_context_id: str,
        replacement_context_id: str,
    ) -> None:
        """Mark one Context as superseded.

        Args:
            superseded_context_id: Context being replaced.
            replacement_context_id: Canonical replacement Context.
        """


class ObsidianVaultLifecycleService:
    """Own vault settings, bootstrap, status, and rebuildable index lifecycle."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_config_store: ObsidianVaultConfigStore,
        save_note: ObsidianLifecycleSaveHook,
        read_note_by_path: ObsidianLifecycleReadHook,
        note_id_from_existing_file: Callable[[Path], str | None],
        mark_context_superseded: ObsidianMarkSupersededHook,
        context_reindex_hook: Callable[[Sequence[str] | None], Awaitable[None]] | None,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        embedding_fingerprint_key: str | None = None,
    ) -> None:
        """Create the vault lifecycle service.

        Args:
            repository: Rebuildable PostgreSQL index repository.
            vault_config_store: Runtime vault location provider.
            save_note: Canonical note save callback.
            read_note_by_path: Canonical note read callback.
            note_id_from_existing_file: Safe frontmatter identifier reader.
            mark_context_superseded: Context lifecycle reconciliation callback.
            context_reindex_hook: Optional Context RAG reindex callback.
            index_maintenance_coordinator: Index maintenance coordinator used by this operation.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._save_note = save_note
        self._read_note_by_path = read_note_by_path
        self._note_id_from_existing_file = note_id_from_existing_file
        self._mark_context_superseded = mark_context_superseded
        self._context_reindex_hook = context_reindex_hook
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._embedding_fingerprint_key = embedding_fingerprint_key

    async def status(self) -> ObsidianVaultStatus:
        """Return local Obsidian vault and index status.

        Returns:
            Current vault and index status.
        """
        config = self._vault_config_store.current()
        indexed, stale, errors = await self._repository.count_by_status()
        index_errors = await self._repository.list_index_errors()
        root = _root_path(config)
        return ObsidianVaultStatus(
            vault_path=str(config.vault_path),
            alexandria_root=config.alexandria_root,
            vault_exists=config.vault_path.exists(),
            alexandria_root_exists=root.exists(),
            indexed_notes=indexed,
            stale_notes=stale,
            error_notes=errors,
            index_errors=tuple(index_errors),
        )

    async def configure(
        self,
        payload: ObsidianVaultSettingsUpdate,
    ) -> ObsidianVaultStatus:
        """Change the runtime Obsidian vault destination.

        Args:
            payload: Vault settings update request.

        Returns:
            Current vault and index status after applying settings.
        """
        config = self._vault_config_store.normalized(
            vault_path=payload.vault_path,
            alexandria_root=payload.alexandria_root,
        )
        if payload.initialize:
            _ensure_vault_layout(config)
        self._vault_config_store.save(config)
        if payload.initialize:
            await self.initialize()
        if payload.reindex:
            await self.reindex()
        return await self.status()

    async def initialize(self) -> ObsidianNote:
        """Create the managed Obsidian folder layout and START_HERE note.

        Returns:
            The canonical START_HERE note.
        """
        config = self._vault_config_store.current()
        _ensure_vault_layout(config)
        start_path = f"{config.alexandria_root}/START_HERE.md"
        absolute = resolve_note_path(config.vault_path, start_path)
        if not absolute.exists():
            return await self._save_note(
                ObsidianSaveNote(
                    note_id="alexandria_start_here",
                    title="Alexandria START HERE",
                    body=start_here_body(),
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    relative_path=start_path,
                    tags=("alexandria", "start-here"),
                    status="active",
                    source="heterarchy-alexandria",
                    frontmatter={"kind": "project_context", "scope": "global"},
                )
            )
        await self.reindex()
        return await self._read_note_by_path(start_path)

    async def reindex(self) -> ObsidianReindexResult:
        """Scan managed Markdown notes and rebuild changed index rows.

        Returns:
            Reindex summary with counts and warnings.
        """
        async with self._index_maintenance_coordinator.operation("vault_reindex"):
            return await self._reindex_serialized()

    async def _reindex_serialized(self) -> ObsidianReindexResult:
        """Run one vault scan while the shared maintenance lease is held.

        Returns:
            ObsidianReindexResult result produced by reindex serialized.
        """
        config = self._vault_config_store.current()
        root = _root_path(config)
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
                await self._record_reindex_error(
                    relative_path,
                    self._note_id_from_existing_file(path),
                    ObsidianValidationError(
                        "CANONICAL_PATH_COLLISION: multiple physical Markdown "
                        f"paths normalize to {relative_path}"
                    ),
                    diagnostics,
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
                await self._record_reindex_error(
                    relative_path,
                    self._note_id_from_existing_file(path),
                    exc,
                    diagnostics,
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
        policy = {
            "chunk_max_chars": DEFAULT_SEARCH_CHUNK_MAX_CHARS,
            "chunk_overlap_chars": DEFAULT_SEARCH_CHUNK_OVERLAP_CHARS,
            "embedding_fingerprint_key": current_embedding_fingerprint_key,
        }
        current_documents: list[CompileDocumentWire] = [
            _compile_document(candidate) for candidate in candidates
        ]
        plan = create_native_compile_plan_provider().compile(
            policy=policy,
            current_documents=current_documents,
            previous={
                "embedding_fingerprint_key": previous_embedding_fingerprint_key,
                "documents": [
                    {
                        "note_id": state.note_id,
                        "relative_path": state.relative_path,
                        "source_hash": state.source_hash,
                        "chunk_hashes": list(state.chunk_hashes),
                        "edge_ids": list(state.edge_ids),
                    }
                    for state in previous_states
                ],
            },
        )
        for diagnostic in plan["diagnostics"]:
            await self._record_reindex_error(
                diagnostic["relative_path"],
                diagnostic["context_id"],
                ValueError(diagnostic["message"]),
                diagnostics,
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
                await self._record_reindex_error(
                    relative_path,
                    candidate.payload.note_id,
                    exc,
                    diagnostics,
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
                await self._record_reindex_error(
                    candidate.payload.relative_path,
                    candidate.payload.note_id,
                    exc,
                    diagnostics,
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
        plan_fingerprint = str(plan["plan_fingerprint"])
        policy_version = str(plan["policy_version"])
        diagnostic_count = len(plan["diagnostics"])
        if self._context_reindex_hook is not None:
            invalidated_note_ids = tuple(
                upsert["note_id"]
                for upsert in plan["upserts"]
                if upsert["embedding"]["action"] == "REEMBED"
            )
            await self._context_reindex_hook(invalidated_note_ids or None)
        receipt: JSONObject = {
            "plan_fingerprint": plan_fingerprint,
            "policy_version": policy_version,
            "applied_at": now_utc().isoformat(),
            "changed_documents": len(plan["upserts"]),
            "removed_documents": len(plan["removals"]),
            "embedding_invalidated_documents": embedding_invalidated_documents,
            "diagnostic_count": diagnostic_count,
        }
        ObsidianReportBundleRunStore(vault_path=config.vault_path).save(
            "compile-receipt:latest", receipt
        )
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

    async def _record_reindex_error(
        self,
        relative_path: str,
        context_id: str | None,
        error: OSError | ValueError | ObsidianIndexWriteError | ObsidianValidationError,
        diagnostics: _ReindexDiagnostics,
    ) -> None:
        """Persist and append one structured per-note reindex failure.

        Args:
            relative_path: Relative path used by this operation.
            context_id: Identifier for context.
            error: Error value being processed.
            diagnostics: Diagnostics used by this operation.
        """
        error_code = index_error_code(error)
        safe_message = _safe_index_error_message(error_code)
        detail = ObsidianIndexError(
            note_path=relative_path,
            context_id=context_id,
            error_code=error_code,
            error_message=safe_message,
            detected_at=now_utc(),
        )
        await self._repository.record_index_error(detail)
        diagnostics.details.append(detail)
        diagnostics.errors.append(
            f"{relative_path}: {detail.error_code.value}: {safe_message}"
        )


def _note_aliases(frontmatter: dict) -> tuple[str, ...]:
    """Decode the alias list consumed by the graph link-name authority.

    Args:
        frontmatter: Note frontmatter mapping.

    Returns:
        Decoded non-blank alias tuple.
    """
    aliases = frontmatter.get("aliases")
    if isinstance(aliases, str):
        return (aliases,) if aliases.strip() else ()
    if isinstance(aliases, list):
        return tuple(
            alias for alias in aliases if isinstance(alias, str) and alias.strip()
        )
    return ()


def _compile_document(candidate: ContextReindexCandidate) -> CompileDocumentWire:
    """Build one strict compile input from an already-parsed note payload.

    Args:
        candidate: Parsed managed-note candidate from the vault scan.

    Returns:
        JSON-serializable compile document input with provided chunks and edges.
    """
    payload = candidate.payload
    return {
        "relative_path": payload.relative_path,
        "note_id": payload.note_id,
        "title": payload.title,
        "alexandria_type": payload.alexandria_type.value,
        "status": payload.status,
        "aliases": list(_note_aliases(payload.frontmatter)),
        "text": None,
        "source_hash": payload.source_hash or "",
        "body": payload.body,
        "frontmatter": payload.frontmatter,
        "edge_seeds": [],
        "provided_chunks": [
            {"chunk_index": chunk.chunk_index, "content_hash": chunk.content_hash}
            for chunk in payload.chunks
        ],
        "provided_edges": [
            {
                "edge_id": edge.edge_id,
                "source_note_id": edge.source_note_id,
                "source_path": edge.source_path,
                "target_note_id": edge.target_note_id,
                "target_path": edge.target_path,
                "relation": edge.relation.value,
                "confidence": edge.confidence,
                "source_kind": edge.source_kind.value,
            }
            for edge in payload.edges
        ],
        "manifest_candidate": {
            "note_id": payload.note_id,
            "relative_path": payload.relative_path,
            "canonical_relative_path": canonical_relative_path(payload.relative_path),
            "is_context": payload.alexandria_type is AlexandriaNoteType.CONTEXT,
            "identity": {
                "scope": manifest_frontmatter_text(payload, "scope"),
                "project": manifest_frontmatter_text(payload, "project"),
                "workspace_id": manifest_frontmatter_text(payload, "workspace_id"),
                "agent_id": manifest_frontmatter_text(payload, "agent_id"),
                "user_id": manifest_frontmatter_text(payload, "user_id"),
                "session_id": manifest_frontmatter_text(payload, "session_id"),
                "content_hash": manifest_frontmatter_text(payload, "content_hash"),
            },
            "supersedes_context_id": manifest_frontmatter_text(
                payload, "supersedes_context_id"
            ),
            "superseded_by_context_id": manifest_frontmatter_text(
                payload, "superseded_by_context_id"
            ),
        },
    }


def _root_path(config: ObsidianVaultConfig) -> Path:
    """Execute root path.

    Args:
        config: Typed configuration used by this operation.

    Returns:
        Path result produced by root path.
    """
    return resolve_note_path(config.vault_path, config.alexandria_root)


def _ensure_vault_layout(config: ObsidianVaultConfig) -> None:
    """Ensure vault layout.

    Args:
        config: Typed configuration used by this operation.
    """
    for folder in default_folders(config.alexandria_root):
        resolve_note_path(config.vault_path, folder).mkdir(parents=True, exist_ok=True)


def index_error_code(
    error: OSError | ValueError | ObsidianIndexWriteError | ObsidianValidationError,
) -> ObsidianIndexErrorCode:
    """Map one indexing failure to its stable error code.

    Args:
        error: Indexing or validation failure.

    Returns:
        Stable public error code.
    """
    message = str(error)
    message_prefix = message.partition(":")[0]
    try:
        return ObsidianIndexErrorCode(message_prefix)
    except ValueError:
        for error_code in ObsidianIndexErrorCode:
            if error_code.value in message:
                return error_code
        if isinstance(error, OSError):
            return ObsidianIndexErrorCode.SOURCE_READ_FAILED
        if isinstance(error, ObsidianIndexWriteError):
            return ObsidianIndexErrorCode.INDEX_WRITE_FAILED
        return ObsidianIndexErrorCode.FRONTMATTER_PARSE_ERROR


def _safe_index_error_message(error_code: ObsidianIndexErrorCode) -> str:
    """Execute safe index error message.

    Args:
        error_code: Error code used by this operation.

    Returns:
        str result produced by safe index error message.
    """
    if error_code is ObsidianIndexErrorCode.INDEX_WRITE_FAILED:
        return "Rebuildable index write failed"
    if error_code is ObsidianIndexErrorCode.SOURCE_READ_FAILED:
        return "Canonical Markdown source could not be read"
    if error_code is ObsidianIndexErrorCode.FRONTMATTER_SECRET_DETECTED:
        return "Frontmatter contains a secret-like field"
    if error_code is ObsidianIndexErrorCode.PATH_SECURITY_VIOLATION:
        return "Managed note path failed security validation"
    if error_code in (
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_ID,
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_CONTENT,
    ):
        return "Context identity conflicts with another managed note"
    if error_code is ObsidianIndexErrorCode.FRONTMATTER_PARSE_ERROR:
        return "Markdown frontmatter could not be validated"
    return "Context frontmatter failed validation"
