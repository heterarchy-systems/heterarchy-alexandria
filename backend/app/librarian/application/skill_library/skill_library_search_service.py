"""Search-first evaluator for reusable skill-library artifacts."""

from __future__ import annotations

from app.librarian.application.skill_library.skill_library_candidate_policy import (
    _dedupe_candidates,
)
from app.librarian.application.skill_library.skill_library_search_contracts import (
    SkillCapabilityBrief,
    SkillSearchBackend,
    SkillSearchCandidate,
    SkillSearchResult,
)
from app.librarian.application.skill_library.skill_library_search_handoff_policy import (
    _decision_explanation,
    _empty_decision_explanation,
    _existing_skill_handoff,
    _query_text,
    _repair_handoff,
    _unique_gap_list,
)
from app.librarian.domain.event_enum.skill_search_enums import SkillSearchDecision
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSearchQuery
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType

__all__ = (
    "SkillCapabilityBrief",
    "SkillLibrarySearchService",
    "SkillSearchBackend",
    "SkillSearchCandidate",
    "SkillSearchDecision",
    "SkillSearchResult",
)


class SkillLibrarySearchService:
    """Evaluate existing skill-library notes before librarian escalation."""

    def __init__(self, search_backend: SkillSearchBackend) -> None:
        """Create evaluator.

        Args:
            search_backend: Obsidian search boundary.
        """
        self._search_backend = search_backend

    async def search_first(self, brief: SkillCapabilityBrief) -> SkillSearchResult:
        """Search reusable skills and classify sufficiency.

        Args:
            brief: Normalized capability need.

        Returns:
            Decision payload; search failures are explicit and never converted to
            empty results.
        """
        query_text = _query_text(brief)
        try:
            hits = await self._search_backend.search(
                ObsidianSearchQuery(
                    query=query_text,
                    limit=max(1, min(brief.limit, 10)),
                    alexandria_type=AlexandriaNoteType.SKILL,
                    project=brief.project,
                ),
                refresh=True,
            )
        except Exception as exc:  # pragma: no cover - exact backend errors vary
            return SkillSearchResult(
                decision=SkillSearchDecision.SEARCH_UNAVAILABLE,
                query=query_text,
                candidates=(),
                recommended_action=(
                    "Run operational readiness/repair before creating a new skill "
                    "so an index failure is not mistaken for a missing skill."
                ),
                gaps=("Skill library search failed",),
                decision_explanation=_empty_decision_explanation(
                    gaps=("Skill library search failed",),
                    limitations=[f"Skill library search unavailable: {exc}"],
                ),
                handoff=_repair_handoff(error_message=str(exc)),
                search_error=str(exc),
            )

        candidates = _dedupe_candidates(hits, brief)
        if not candidates:
            return SkillSearchResult(
                decision=SkillSearchDecision.NOT_FOUND,
                query=query_text,
                candidates=(),
                recommended_action=(
                    "No reusable skill was found in healthy search; create a "
                    "draft skill-acquisition job if the capability is still needed."
                ),
                gaps=("No non-archived skill candidates matched the capability brief",),
                decision_explanation=_empty_decision_explanation(
                    gaps=[
                        "No non-archived skill candidates matched the capability brief"
                    ],
                    limitations=["No reusable skill candidate was available to score"],
                ),
            )

        top = candidates[0]
        if top.sufficiency_score >= 8 and not top.gaps:
            return SkillSearchResult(
                decision=SkillSearchDecision.FOUND_SUFFICIENT,
                query=query_text,
                candidates=tuple(candidates),
                recommended_action=(
                    f"Reuse existing skill '{top.title}' at {top.path}; do not "
                    "create a skill-acquisition job."
                ),
                gaps=(),
                decision_explanation=_decision_explanation(
                    candidates=tuple(candidates),
                    gaps=(),
                ),
                handoff=_existing_skill_handoff(candidate=top, brief=brief),
            )
        gaps = _unique_gap_list(candidates)
        return SkillSearchResult(
            decision=SkillSearchDecision.FOUND_PARTIAL,
            query=query_text,
            candidates=tuple(candidates),
            recommended_action=(
                "Related skills exist but do not fully satisfy the capability "
                "brief; pass candidates and gaps into librarian acquisition."
            ),
            gaps=tuple(gaps),
            decision_explanation=_decision_explanation(
                candidates=tuple(candidates),
                gaps=tuple(gaps),
            ),
            handoff=_existing_skill_handoff(candidate=top, brief=brief),
        )
