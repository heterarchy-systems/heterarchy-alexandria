"""Unit tests for the canonical Obsidian reconciliation mutation adapter."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio
from app.memory.application.reconciliation.runtime.obsidian_memory_canonical_mutation_gateway import (
    ObsidianMemoryCanonicalMutationGateway,
)
from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    MemoryCandidate,
    MemorySourceReference,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import MemoryRelationType
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianNotFoundError

NOW = datetime(2026, 7, 25, tzinfo=UTC)


class RecordingObsidianService:
    """Record canonical note payloads while emulating read and supersede behavior."""

    def __init__(self) -> None:
        self.notes: dict[str, ObsidianNote] = {}
        self.saved_payloads: list[ObsidianSaveNote] = []
        self.superseded: list[tuple[str, str]] = []

    async def save_note(self, payload: ObsidianSaveNote) -> ObsidianNote:
        self.saved_payloads.append(payload)
        note_id = payload.note_id or "generated-note"
        note = ObsidianNote(
            note_id=note_id,
            relative_path=(
                payload.relative_path or f"Alexandria/Contexts/{note_id}.md"
            ),
            alexandria_type=payload.alexandria_type,
            title=payload.title,
            status=payload.status,
            tags=payload.tags,
            project=payload.project,
            source=payload.source,
            content_hash="content-hash",
            frontmatter=payload.frontmatter,
            body=payload.body,
            index_status=ObsidianIndexStatus.INDEXED,
            error_message=None,
            size_bytes=len(payload.body.encode("utf-8")),
            modified_at=NOW,
            indexed_at=NOW,
        )
        self.notes[note_id] = note
        return note

    async def read_note(self, note_id: str) -> ObsidianNote:
        note = self.notes.get(note_id)
        if note is None:
            raise ObsidianNotFoundError(f"Missing note: {note_id}")
        return note

    async def supersede_context(
        self,
        note_id: str,
        replacement_note_id: str,
    ) -> tuple[ObsidianNote, ObsidianNote]:
        self.superseded.append((note_id, replacement_note_id))
        return self.notes[note_id], self.notes[replacement_note_id]


def _source(source_id: str) -> MemorySourceReference:
    return MemorySourceReference(
        source_type="user",
        source_id=source_id,
        title=f"Source {source_id}",
        detail_path=f"Contexts/{source_id}.md",
        observed_at=NOW,
    )


def _candidate() -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id="candidate-1",
        title="Storage decision",
        body="heterarchy-alexandria uses PostgreSQL.",
        canonical_claims=(
            CanonicalClaim(
                subject="heterarchy-alexandria",
                predicate="uses",
                object="PostgreSQL",
                scope=ContextScope.PROJECT,
                project="heterarchy-alexandria",
                valid_from=NOW,
            ),
        ),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        tags=("memory",),
        source_refs=(_source("source-1"),),
        recorded_at=NOW,
        observed_at=NOW,
        valid_from=NOW,
        valid_to=None,
        requested_lifecycle="active",
        content_hash="candidate-hash",
    )


def _context_note(note_id: str, title: str) -> ObsidianNote:
    return ObsidianNote(
        note_id=note_id,
        relative_path=f"Alexandria/Contexts/{note_id}.md",
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title=title,
        status="active",
        tags=[],
        project="heterarchy-alexandria",
        source="test",
        content_hash=f"hash-{note_id}",
        frontmatter={"scope": "PROJECT", "project": "heterarchy-alexandria"},
        body=title,
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=len(title.encode("utf-8")),
        modified_at=NOW,
        indexed_at=NOW,
    )


def test_gateway_writes_temporal_claim_and_conflict_frontmatter() -> None:
    async def scenario() -> None:
        service = RecordingObsidianService()
        service.notes["context-old"] = _context_note("context-old", "Old")
        gateway = ObsidianMemoryCanonicalMutationGateway(service)

        context_id = await gateway.create_context(
            _candidate(),
            lifecycle_status="pending_review",
            supersedes_context_id="obsidian:context-old",
            conflict_set_ids=("conflict-1",),
            relation=MemoryRelationType.SUPERSEDES,
            related_context_id="obsidian:context-old",
        )

        assert context_id == "obsidian:candidate-1"
        payload = service.saved_payloads[-1]
        assert payload.alexandria_type is AlexandriaNoteType.CONTEXT
        assert payload.status == "pending_review"
        assert payload.frontmatter["scope"] == "PROJECT"
        assert payload.frontmatter["supersedes_context_id"] == "context-old"
        assert payload.frontmatter["conflict_set_ids"] == ["conflict-1"]
        assert payload.frontmatter["valid_from"] == NOW.isoformat()
        assert payload.frontmatter["canonical_claims"]
        assert payload.frontmatter["supersedes"] == [
            {
                "id": "context-old",
                "path": "Alexandria/Contexts/context-old.md",
                "relation": "supersedes",
            }
        ]
        assert await gateway.verify(context_id) is True

    anyio.run(scenario)


def test_gateway_merges_evidence_idempotently_and_preserves_note_identity() -> None:
    async def scenario() -> None:
        service = RecordingObsidianService()
        gateway = ObsidianMemoryCanonicalMutationGateway(service)
        context_id = await gateway.create_context(
            _candidate(),
            lifecycle_status="active",
        )

        await gateway.merge_evidence(
            context_id,
            (_source("source-1"), _source("source-2")),
        )
        merged_id = await gateway.merge_evidence(
            context_id,
            (_source("source-2"),),
        )

        assert merged_id == context_id
        payload = service.saved_payloads[-1]
        assert payload.note_id == "candidate-1"
        assert payload.relative_path == "Alexandria/Contexts/candidate-1.md"
        assert payload.frontmatter["evidence_refs"] == [
            "Contexts/source-1.md",
            "Contexts/source-2.md",
        ]
        source_refs = payload.frontmatter["memory_source_refs"]
        assert isinstance(source_refs, list)
        assert len(source_refs) == 2

    anyio.run(scenario)


def test_gateway_translates_source_qualified_supersede_ids() -> None:
    async def scenario() -> None:
        service = RecordingObsidianService()
        old = _candidate()
        service.notes["context-old"] = _context_note("context-old", "Old")
        gateway = ObsidianMemoryCanonicalMutationGateway(service)
        await gateway.create_context(old, lifecycle_status="active")

        await gateway.supersede(
            "obsidian:context-old",
            "obsidian:candidate-1",
        )

        assert service.superseded == [("context-old", "candidate-1")]

    anyio.run(scenario)
