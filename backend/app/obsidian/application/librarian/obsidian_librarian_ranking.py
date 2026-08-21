"""Rank fusion for Obsidian Librarian multi-query retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from app.obsidian.domain.entities.obsidian_note import ObsidianSearchHit

RECIPROCAL_RANK_FUSION_CONSTANT = 60


@dataclass(slots=True)
class _LibrarianHitEvidence:
    """Mutable evidence accumulated across bounded Librarian search variants."""

    representative: ObsidianSearchHit
    fused_score: float
    first_seen: int


def fuse_librarian_search_hits(
    ranked_hit_lists: list[list[ObsidianSearchHit]],
    limit: int,
) -> list[ObsidianSearchHit]:
    """Fuse ranked query-variant results and return unique source notes.

    Args:
        ranked_hit_lists: Search results ordered by relevance for each query.
        limit: Maximum unique notes to return.

    Returns:
        Unique notes ranked by reciprocal-rank evidence across query variants.
    """
    evidence_by_note_id: dict[str, _LibrarianHitEvidence] = {}
    first_seen = 0
    for hits in ranked_hit_lists:
        seen_note_ids: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            note_id = hit.note.note_id
            if note_id in seen_note_ids:
                continue
            seen_note_ids.add(note_id)
            contribution = 1.0 / (RECIPROCAL_RANK_FUSION_CONSTANT + rank)
            evidence = evidence_by_note_id.get(note_id)
            if evidence is None:
                evidence_by_note_id[note_id] = _LibrarianHitEvidence(
                    representative=hit,
                    fused_score=contribution,
                    first_seen=first_seen,
                )
                first_seen += 1
                continue
            evidence.fused_score += contribution
            if hit.score > evidence.representative.score:
                evidence.representative = hit

    ranked_evidence = sorted(
        evidence_by_note_id.values(),
        key=lambda evidence: (-evidence.fused_score, evidence.first_seen),
    )
    return [evidence.representative for evidence in ranked_evidence[:limit]]
