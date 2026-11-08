"""Candidate recall projection and temporal persistence regressions."""

from __future__ import annotations

from dataclasses import replace

import anyio
from tests.memory.reconciliation.test_memory_temporal_recall_service import (
    JULY_1,
    JULY_10,
    JULY_20,
    JULY_21,
    JULY_25,
    _context,
    _match,
)

from app.memory.application.reconciliation.candidates.memory_candidate_recall_service import (
    MemoryCandidateRecallService,
)
from app.memory.domain.entities.context_read_models import (
    ContextPack,
    ContextSearchMatch,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemoryRecallCandidate,
    MemoryTemporalState,
)
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.repositories.contexts.memory_candidate_recall_source import (
    IMemoryCandidateRecallSource,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_temporal_repository import (
    IMemoryReconciliationTemporalRepository,
)


class StaticRecallSource(IMemoryCandidateRecallSource):
    """Return ranked matches through the candidate recall boundary."""

    def __init__(self, matches: tuple[ContextSearchMatch, ...]) -> None:
        self.matches = matches
        self.calls: list[tuple[MemoryCandidate, str, int]] = []

    async def recall(
        self,
        candidate: MemoryCandidate,
        query: str,
        limit: int,
    ) -> ContextPack:
        self.calls.append((candidate, query, limit))
        return ContextPack(
            query=query,
            strategy=RagStrategy.HYBRID,
            effective_strategy=RagStrategy.HYBRID,
            warnings=(),
            recall_scopes=(candidate.scope,),
            matches=self.matches,
            context_pack="",
        )


class TemporalPersistenceFake(IMemoryReconciliationTemporalRepository):
    """Expose point and bounded reads at the temporal persistence port."""

    def __init__(self, states: dict[str, MemoryTemporalState]) -> None:
        self.states = states
        self.point_reads: list[str] = []
        self.bulk_reads: list[tuple[str, ...]] = []

    async def upsert_temporal_state(
        self,
        state: MemoryTemporalState,
    ) -> MemoryTemporalState:
        raise AssertionError("candidate recall must not write temporal state")

    async def get_temporal_state(
        self,
        context_id: str,
    ) -> MemoryTemporalState | None:
        self.point_reads.append(context_id)
        return self.states.get(context_id)

    async def get_temporal_states(
        self,
        context_ids: tuple[str, ...],
    ) -> dict[str, MemoryTemporalState]:
        self.bulk_reads.append(context_ids)
        return {
            context_id: self.states[context_id]
            for context_id in context_ids
            if context_id in self.states
        }


def _candidate() -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id="candidate-1",
        title="proposed title",
        body="proposed body",
        canonical_claims=(),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        tags=(),
        source_refs=(),
        recorded_at=JULY_25,
        observed_at=None,
        valid_from=None,
        valid_to=None,
        requested_lifecycle="CURRENT",
        content_hash="candidate-hash",
    )


def test_recall_batches_temporal_overlays_after_identity_filter_and_dedup() -> None:
    first = _context(
        "context:first",
        created_at=JULY_1,
        metadata={
            "content_hash": "first-hash",
            "source": "vault",
            "relative_path": "facts/first.md",
        },
    )
    invalid_identity = replace(first, id="context:invalid", project="other-project")
    duplicate = replace(first, title="later duplicate", content="later duplicate body")
    missing_overlay = _context(
        "context:missing",
        created_at=JULY_10,
        metadata={"content_hash": "missing-hash"},
    )
    last = _context(
        "context:last",
        created_at=JULY_25,
        metadata={"content_hash": "candidate-hash"},
    )
    states = {
        "context:last": MemoryTemporalState(
            context_id="context:last",
            recorded_at=JULY_21,
            observed_at=JULY_20,
            valid_from=JULY_21,
            valid_to=None,
            is_current=True,
        ),
        "context:first": MemoryTemporalState(
            context_id="context:first",
            recorded_at=JULY_20,
            observed_at=JULY_21,
            valid_from=JULY_1,
            valid_to=JULY_25,
            is_current=False,
            supersedes=("ancestor-z", "ancestor-a", "ancestor-z"),
        ),
    }
    source = StaticRecallSource(
        (
            _match(first, 0),
            _match(invalid_identity, 1),
            _match(duplicate, 2),
            _match(missing_overlay, 3),
            _match(last, 4),
        )
    )
    repository = TemporalPersistenceFake(states)
    candidate = _candidate()
    service = MemoryCandidateRecallService(source, repository)

    async def scenario() -> tuple[MemoryRecallCandidate, ...]:
        return await service.recall(candidate, limit=7)

    recalled = anyio.run(scenario)

    assert source.calls == [(candidate, "proposed title proposed body", 7)]
    assert tuple(item.context_id for item in recalled) == (
        "context:first",
        "context:missing",
        "context:last",
    )
    assert tuple(item.title for item in recalled) == (
        "context:first",
        "context:missing",
        "context:last",
    )
    assert recalled[0].body == first.content
    assert recalled[0].content_hash == "first-hash"
    assert recalled[0].source_identity == "vault"
    assert recalled[0].source_refs[0].detail_path == "facts/first.md"
    assert recalled[0].recorded_at == JULY_20
    assert recalled[0].observed_at == JULY_21
    assert recalled[0].valid_from == JULY_1
    assert recalled[0].valid_to == JULY_25
    assert recalled[0].lineage_ancestors == ("ancestor-a", "ancestor-z")
    assert recalled[1].recorded_at == missing_overlay.created_at
    assert recalled[1].observed_at is None
    assert recalled[1].valid_from is None
    assert recalled[1].valid_to is None
    assert recalled[1].lineage_ancestors == ()
    assert recalled[2].recall_reasons == (
        "rank-4",
        "exact_content_hash",
        "canonical_claims_unavailable",
    )
    assert repository.bulk_reads == [
        ("context:first", "context:missing", "context:last")
    ]
    assert repository.point_reads == []


def test_recall_skips_temporal_read_when_no_candidate_identity_matches() -> None:
    invalid_identity = replace(
        _context("context:invalid", created_at=JULY_1),
        project="other-project",
    )
    source = StaticRecallSource((_match(invalid_identity, 0),))
    repository = TemporalPersistenceFake({})
    service = MemoryCandidateRecallService(source, repository)

    async def scenario() -> tuple[MemoryRecallCandidate, ...]:
        return await service.recall(_candidate())

    recalled = anyio.run(scenario)

    assert recalled == ()
    assert repository.bulk_reads == []
    assert repository.point_reads == []
