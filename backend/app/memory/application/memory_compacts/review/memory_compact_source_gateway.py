"""Compact source observations dispatch only to existing canonical source owners."""

from hashlib import sha256

from pydantic import TypeAdapter

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactSourceObservation,
)
from app.memory.application.reconciliation.cycles.memory_cycle_source_fence import (
    context_content_hash,
)
from app.memory.domain.entities.context_read_models import (
    ContextRecord,
    RagDependencyHealth,
)
from app.memory.domain.entities.memory_compact import MemoryCompactSourceRef
from app.memory.domain.repositories.memory_compacts.memory_compact_query_repository import (
    IMemoryCompactQueryRepository,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianReadPort
from app.shared.serialization.orjson_codec import dumps_canonical_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_RAG = TypeAdapter(RagDependencyHealth)
_CONTEXT = TypeAdapter(ContextRecord)


class CanonicalMemoryCompactSourceReader:
    """Acquire current facts/revisions without trusting caller observation fields."""

    def __init__(
        self,
        obsidian: ObsidianReadPort,
        contexts: ContextService,
        compacts: IMemoryCompactQueryRepository,
    ) -> None:
        """Bind existing source owners.

        Args:
            obsidian: Exact canonical Markdown reader.
            contexts: Existing SQL/Obsidian Context dispatcher.
            compacts: Durable Compact source reader.
        """
        self._obsidian = obsidian
        self._contexts = contexts
        self._compacts = compacts

    async def __call__(
        self, source: MemoryCompactSourceRef
    ) -> MemoryCompactSourceObservation:
        """Return exact source evidence or explicit unavailable state.

        Args:
            source: Declared identity and canonical detail selector.

        Returns:
            Current semantic hash and source revision, with no inferred identities.
        """
        kind = source.source_type.casefold()
        context_selector = source.detail_path in {
            f"context:{source.source_id}",
            f"/memory/contexts/{source.source_id}",
        }
        if (
            kind in {"context", "obsidian"}
            or context_selector
            or source.source_id.startswith("obsidian:")
        ):
            if source.source_id.startswith("obsidian:") or kind == "obsidian":
                note_id = source.source_id.removeprefix("obsidian:")
                note = await self._obsidian.read_note(note_id)
                allowed = {
                    note.relative_path,
                    f"/obsidian/notes/{note_id}",
                    f"/memory/contexts/obsidian:{note_id}",
                    f"context:obsidian:{note_id}",
                }
                if source.detail_path not in allowed:
                    return self._unavailable(source, "source_selector_mismatch")
                return self._observed(
                    source,
                    note.content_hash,
                    note.source_hash or note.content_hash,
                    scope=str(
                        note.frontmatter.get("scope")
                        or ("PROJECT" if note.project else "GLOBAL")
                    ),
                    visibility=str(
                        note.frontmatter.get("visibility")
                        or note.frontmatter.get("scope")
                        or ("PROJECT" if note.project else "GLOBAL")
                    ),
                )
            if not context_selector:
                return self._unavailable(source, "source_selector_mismatch")
            context = await self._contexts.get(source.source_id)
            if context.id != source.source_id:
                return self._unavailable(source, "source_identity_mismatch")
            revision: JSONValue = loads_json(
                _CONTEXT.dump_json(
                    context, exclude={"last_accessed_at", "access_count"}
                )
            )
            return self._observed(
                source,
                context_content_hash(context),
                sha256(dumps_canonical_json(revision)).hexdigest(),
                scope=context.scope.value,
                visibility=context.visibility.value,
            )
        if kind == "memory_compact":
            if source.detail_path != f"/memory/compacts/{source.source_id}":
                return self._unavailable(source, "source_selector_mismatch")
            compact = await self._compacts.get(source.source_id)
            if compact is None:
                return self._unavailable(source, "source_compact_missing")
            body_hash = sha256(compact.markdown_body.encode()).hexdigest()
            source_ref_pairs: list[JSONValue] = [
                [ref.source_id, ref.source_hash] for ref in compact.source_refs
            ]
            compact_revision: JSONObject = {
                "id": compact.id,
                "body": compact.markdown_body,
                "project": compact.project,
                "covered_from": compact.covered_from.isoformat(),
                "covered_to": compact.covered_to.isoformat(),
                "source_refs": source_ref_pairs,
            }
            return self._observed(
                source,
                body_hash,
                sha256(dumps_canonical_json(compact_revision)).hexdigest(),
            )
        if (
            kind == "memory_steward_readiness"
            and source.detail_path
            == "/memory/contexts/rag/status + /memory/compacts/current"
        ):
            health = await self._contexts.rag_health_with_index_status()
            fingerprint = sha256(_RAG.dump_json(health)).hexdigest()
            return self._observed(source, fingerprint, fingerprint)
        return self._unavailable(source, "unsupported_source_owner")

    @staticmethod
    def _observed(
        source: MemoryCompactSourceRef,
        content_hash: str,
        revision: str,
        *,
        scope: str | None = None,
        visibility: str | None = None,
    ) -> MemoryCompactSourceObservation:
        """Build an available source observation with current hash and revision.

        Args:
            source: Declared source reference being observed.
            content_hash: Current canonical content hash of the source.
            revision: Current canonical source revision fingerprint.
            scope: Optional resolved source scope.
            visibility: Optional resolved source visibility.

        Returns:
            Available source observation record.
        """
        return MemoryCompactSourceObservation(
            source_id=source.source_id,
            detail_path=source.detail_path,
            current_source_hash=content_hash,
            source_revision=revision,
            source_scope=scope,
            source_visibility=visibility,
        )

    @staticmethod
    def _unavailable(
        source: MemoryCompactSourceRef, reason: str
    ) -> MemoryCompactSourceObservation:
        """Build an unavailable source observation with an explicit reason code.

        Args:
            source: Declared source reference that could not be verified.
            reason: Machine-readable unavailability reason code.

        Returns:
            Unavailable source observation record.
        """
        return MemoryCompactSourceObservation(
            source_id=source.source_id,
            detail_path=source.detail_path,
            available=False,
            unavailable_reason=reason,
        )
