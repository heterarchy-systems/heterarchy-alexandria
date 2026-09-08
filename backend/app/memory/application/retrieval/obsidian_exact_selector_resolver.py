"""Canonical Obsidian source adapter for exact high-level recall selectors."""

from __future__ import annotations

from app.memory.application.integration.obsidian_context_read_mapper import (
    context_record_from_obsidian_note,
)
from app.memory.application.retrieval.chunker import chunk_markdown
from app.memory.domain.contracts.context_recall_contracts import ScopeIdentity
from app.memory.domain.contracts.recall_contracts import (
    RecallExactSelector,
    RecallExactSelectorResolver,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextSearchMatch,
)
from app.obsidian.application.notes.lifecycle.obsidian_canonical_note_path import (
    canonical_managed_note_path,
)
from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexStatus
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)


class ObsidianExactSelectorResolver(RecallExactSelectorResolver):
    """Read exact canonical Markdown through Obsidian's source-owned facade."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        canonical_identity_service: ObsidianCanonicalIdentityService,
    ) -> None:
        """Create the exact source resolver from existing Obsidian authorities."""
        self._obsidian_service = obsidian_service
        self._canonical_identity_service = canonical_identity_service

    async def resolve(
        self,
        selector: RecallExactSelector,
        scope_identity: ScopeIdentity,
    ) -> tuple[ContextSearchMatch, ...]:
        """Read one exact note and map it into the existing Context read model."""
        del scope_identity
        try:
            note = await self._read_selector(selector)
        except ObsidianNotFoundError:
            return ()
        except ObsidianValidationError as exc:
            raise MemoryContextValidationError(str(exc)) from exc
        if note is None:
            return ()
        return (self._match_from_note(note),)

    async def _read_selector(
        self, selector: RecallExactSelector
    ) -> ObsidianNote | None:
        """Resolve selector precedence through the canonical source facade."""
        if selector.note_id is not None and selector.note_id.strip():
            return await self._obsidian_service.read_note(
                selector.note_id.strip().removeprefix("obsidian:")
            )
        if selector.path is not None and selector.path.strip():
            canonical_path = canonical_managed_note_path(
                selector.path.strip(),
                alexandria_root=self._obsidian_service.vault_location().alexandria_root,
            )
            return await self._obsidian_service.read_note_by_path(canonical_path)
        identity = selector.logical_identity
        if identity is None:
            raise MemoryContextValidationError(
                "exact selector requires note_id, path, or logical_identity"
            )
        resolved = await self._canonical_identity_service.resolve_logical_identity(
            identity
        )
        if resolved.resolution == "AMBIGUOUS_CANONICAL_IDENTITY":
            raise MemoryContextValidationError(
                "AMBIGUOUS_CANONICAL_IDENTITY: exact logical identity has multiple matches"
            )
        if resolved.existing_note_id is None:
            return None
        return await self._obsidian_service.read_note(resolved.existing_note_id)

    def _match_from_note(self, note: ObsidianNote) -> ContextSearchMatch:
        """Build one exact match without claiming an index timestamp."""
        context = context_record_from_obsidian_note(note)
        chunks = chunk_markdown(note.title, note.body)
        if chunks:
            source_chunk = chunks[0]
            chunk = ContextChunkRecord(
                id=f"{context.id}:source:{source_chunk.chunk_index}",
                context_id=context.id,
                chunk_index=source_chunk.chunk_index,
                heading=source_chunk.heading,
                content=source_chunk.content,
                token_count=source_chunk.token_count,
                content_hash=source_chunk.content_hash,
                chunk_metadata=source_chunk.metadata,
                created_at=context.updated_at,
            )
        else:
            chunk = ContextChunkRecord(
                id=f"{context.id}:source:0",
                context_id=context.id,
                chunk_index=0,
                heading=note.title,
                content=note.body,
                token_count=0,
                content_hash=note.content_hash,
                chunk_metadata={},
                created_at=context.updated_at,
            )
        why = "Exact canonical source selector read"
        if note.index_status is ObsidianIndexStatus.UNINDEXED:
            why += "; retrieval projection is UNINDEXED"
        elif note.index_status is ObsidianIndexStatus.STALE:
            why += "; retrieval projection is STALE"
        return ContextSearchMatch(
            context=context,
            chunk=chunk,
            score=1.0,
            fts_score=None,
            vector_score=None,
            why_retrieved=why,
        )
