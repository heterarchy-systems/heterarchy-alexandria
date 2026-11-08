"""Map parsed vault notes and prior state to canonical native compile inputs."""

from __future__ import annotations

from collections.abc import Sequence

from app.obsidian.application.notes.lifecycle.obsidian_context_reindex_manifest import (
    ContextReindexCandidate,
    manifest_frontmatter_text,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianCompiledDocumentState,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.paths import canonical_relative_path
from app.shared.infrastructure.native_compute.native_compile_plan import (
    CompileContextIdentityWire,
    CompileDocumentWire,
    CompileManifestCandidateWire,
    CompilePolicyWire,
    CompileProvidedChunkWire,
    CompileProvidedEdgeWire,
    PreviousCompilationSnapshotWire,
    PreviousDocumentStateWire,
)
from app.shared.search.markdown_text_chunking import (
    DEFAULT_SEARCH_CHUNK_MAX_CHARS,
    DEFAULT_SEARCH_CHUNK_OVERLAP_CHARS,
)
from app.shared.types.extra_types import JSONObject


class VaultCompileInputMapper:
    """Build the typed inputs consumed by the Rust compile-plan authority."""

    @staticmethod
    def aliases(frontmatter: JSONObject) -> tuple[str, ...]:
        """Decode the alias list consumed by graph link-name resolution.

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

    @classmethod
    def document(cls, candidate: ContextReindexCandidate) -> CompileDocumentWire:
        """Build one strict compile input from a parsed note payload.

        Args:
            candidate: Parsed managed-note candidate from the vault scan.

        Returns:
            JSON-serializable compile document input with provided chunks and edges.
        """
        payload = candidate.payload
        return CompileDocumentWire(
            relative_path=payload.relative_path,
            note_id=payload.note_id,
            title=payload.title,
            alexandria_type=payload.alexandria_type.value,
            status=payload.status,
            aliases=list(cls.aliases(payload.frontmatter)),
            text=None,
            source_hash=payload.source_hash or "",
            body=payload.body,
            frontmatter=payload.frontmatter,
            edge_seeds=[],
            provided_chunks=[
                CompileProvidedChunkWire(
                    chunk_index=chunk.chunk_index,
                    content_hash=chunk.content_hash,
                )
                for chunk in payload.chunks
            ],
            provided_edges=[
                CompileProvidedEdgeWire(
                    edge_id=edge.edge_id,
                    source_note_id=edge.source_note_id,
                    source_path=edge.source_path,
                    target_note_id=edge.target_note_id,
                    target_path=edge.target_path,
                    relation=edge.relation.value,
                    confidence=edge.confidence,
                    source_kind=edge.source_kind.value,
                )
                for edge in payload.edges
            ],
            manifest_candidate=CompileManifestCandidateWire(
                note_id=payload.note_id,
                relative_path=payload.relative_path,
                canonical_relative_path=canonical_relative_path(payload.relative_path),
                is_context=payload.alexandria_type is AlexandriaNoteType.CONTEXT,
                identity=CompileContextIdentityWire(
                    scope=manifest_frontmatter_text(payload, "scope"),
                    project=manifest_frontmatter_text(payload, "project"),
                    workspace_id=manifest_frontmatter_text(payload, "workspace_id"),
                    agent_id=manifest_frontmatter_text(payload, "agent_id"),
                    user_id=manifest_frontmatter_text(payload, "user_id"),
                    session_id=manifest_frontmatter_text(payload, "session_id"),
                    content_hash=manifest_frontmatter_text(payload, "content_hash"),
                ),
                supersedes_context_id=manifest_frontmatter_text(
                    payload, "supersedes_context_id"
                ),
                superseded_by_context_id=manifest_frontmatter_text(
                    payload, "superseded_by_context_id"
                ),
            ),
        )

    @staticmethod
    def policy(embedding_fingerprint_key: str) -> CompilePolicyWire:
        """Construct the current vault compile policy.

        Args:
            embedding_fingerprint_key: Active embedding identity or disabled marker.

        Returns:
            Canonical typed compile policy.
        """
        return CompilePolicyWire(
            chunk_max_chars=DEFAULT_SEARCH_CHUNK_MAX_CHARS,
            chunk_overlap_chars=DEFAULT_SEARCH_CHUNK_OVERLAP_CHARS,
            embedding_fingerprint_key=embedding_fingerprint_key,
        )

    @staticmethod
    def previous_snapshot(
        states: Sequence[ObsidianCompiledDocumentState],
        embedding_fingerprint_key: str,
    ) -> PreviousCompilationSnapshotWire:
        """Construct the previous-state snapshot for native compilation.

        Args:
            states: Previously compiled PostgreSQL document states.
            embedding_fingerprint_key: Previous embedding identity or incomplete marker.

        Returns:
            Canonical typed previous compilation snapshot.
        """
        return PreviousCompilationSnapshotWire(
            embedding_fingerprint_key=embedding_fingerprint_key,
            documents=[
                PreviousDocumentStateWire(
                    note_id=state.note_id,
                    relative_path=state.relative_path,
                    source_hash=state.source_hash,
                    chunk_hashes=list(state.chunk_hashes),
                    edge_ids=list(state.edge_ids),
                )
                for state in states
            ],
        )
