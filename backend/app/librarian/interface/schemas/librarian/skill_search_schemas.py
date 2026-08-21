"""Search-first skill capability API schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.librarian.application.skill_library.skill_library_search_contracts import (
    SkillCapabilityBrief,
    SkillSearchCandidate,
    SkillSearchResult,
)
from app.librarian.domain.event_enum.skill_acquisition_enums import RiskLevel
from app.librarian.domain.event_enum.skill_search_enums import SkillSearchDecision
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.types.extra_types import JSONValue


class SkillCapabilitySearchRequest(StrictSchemaModel):
    """Search-first request before creating a skill-acquisition job."""

    capability: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Capability for this skill capability search request."),
    ]
    task_goal: Annotated[
        str | None,
        described_field("Task goal for this skill capability search request."),
    ] = None
    project: Annotated[
        str | None, described_field("Project for this skill capability search request.")
    ] = None
    environment: Annotated[
        str | None,
        described_field("Environment for this skill capability search request."),
    ] = None
    required_tools: Annotated[
        list[str],
        described_field("Required tools for this skill capability search request."),
    ] = schema_list_default()
    constraints: Annotated[
        list[str],
        described_field("Constraints for this skill capability search request."),
    ] = schema_list_default()
    risk_tolerance: Annotated[
        RiskLevel,
        described_field("Risk tolerance for this skill capability search request."),
    ] = RiskLevel.MEDIUM
    success_criteria: Annotated[
        list[str],
        described_field("Success criteria for this skill capability search request."),
    ] = schema_list_default()
    limit: Annotated[
        int,
        described_field("Limit for this skill capability search request.", ge=1, le=10),
    ] = 5

    def to_brief(self) -> SkillCapabilityBrief:
        """Return the internal normalized capability brief.

        Returns:
            Application search brief.
        """
        return SkillCapabilityBrief(
            capability=self.capability,
            task_goal=self.task_goal,
            project=self.project,
            environment=self.environment,
            required_tools=tuple(self.required_tools),
            constraints=tuple(self.constraints),
            risk_tolerance=self.risk_tolerance,
            success_criteria=tuple(self.success_criteria),
            limit=self.limit,
        )


class SkillSearchCandidateResponse(StrictSchemaModel):
    """Normalized skill candidate returned by search-first evaluation."""

    id: Annotated[
        str,
        described_field("Stable identifier for this skill search candidate response."),
    ]
    path: Annotated[
        str, described_field("Path for this skill search candidate response.")
    ]
    title: Annotated[
        str, described_field("Title for this skill search candidate response.")
    ]
    status: Annotated[
        str, described_field("Status for this skill search candidate response.")
    ]
    version: Annotated[
        str | None, described_field("Version for this skill search candidate response.")
    ]
    project: Annotated[
        str | None, described_field("Project for this skill search candidate response.")
    ]
    required_tools: Annotated[
        list[str],
        described_field("Required tools for this skill search candidate response."),
    ]
    risk_level: Annotated[
        RiskLevel,
        described_field("Risk level for this skill search candidate response."),
    ]
    evidence: Annotated[
        list[str], described_field("Evidence for this skill search candidate response.")
    ]
    matched_terms: Annotated[
        list[str],
        described_field("Matched terms for this skill search candidate response."),
    ]
    limitations: Annotated[
        list[str],
        described_field("Limitations for this skill search candidate response."),
    ]
    score: Annotated[
        float, described_field("Score for this skill search candidate response.")
    ]
    sufficiency_score: Annotated[
        int,
        described_field("Sufficiency score for this skill search candidate response."),
    ]
    hard_gates: Annotated[
        dict[str, JSONValue],
        described_field("Hard gates for this skill search candidate response."),
    ]
    why_match: Annotated[
        list[str],
        described_field("Why match for this skill search candidate response."),
    ]
    gaps: Annotated[
        list[str], described_field("Gaps for this skill search candidate response.")
    ]
    recommended_action: Annotated[
        str,
        described_field("Recommended action for this skill search candidate response."),
    ]


class SkillCapabilitySearchResponse(StrictSchemaModel):
    """Search-first sufficiency result for one capability brief."""

    decision: Annotated[
        SkillSearchDecision,
        described_field("Decision for this skill capability search response."),
    ]
    query: Annotated[
        str, described_field("Query for this skill capability search response.")
    ]
    candidates: Annotated[
        list[SkillSearchCandidateResponse],
        described_field("Candidates for this skill capability search response."),
    ]
    recommended_action: Annotated[
        str,
        described_field(
            "Recommended action for this skill capability search response."
        ),
    ]
    gaps: Annotated[
        list[str], described_field("Gaps for this skill capability search response.")
    ]
    decision_explanation: Annotated[
        dict[str, JSONValue],
        described_field(
            "Decision explanation for this skill capability search response."
        ),
    ]
    handoff: Annotated[
        dict[str, JSONValue] | None,
        described_field("Handoff for this skill capability search response."),
    ]
    search_error: Annotated[
        str | None,
        described_field("Search error for this skill capability search response."),
    ]


def skill_search_candidate_response(
    candidate: SkillSearchCandidate,
) -> SkillSearchCandidateResponse:
    """Map one application candidate to the public response schema.

    Args:
        candidate: Application search candidate.

    Returns:
        Public candidate response schema.
    """
    return SkillSearchCandidateResponse(
        id=candidate.id,
        path=candidate.path,
        title=candidate.title,
        status=candidate.status,
        version=candidate.version,
        project=candidate.project,
        required_tools=list(candidate.required_tools),
        risk_level=candidate.risk_level,
        evidence=list(candidate.evidence),
        matched_terms=list(candidate.matched_terms),
        limitations=list(candidate.limitations),
        score=candidate.score,
        sufficiency_score=candidate.sufficiency_score,
        hard_gates=candidate.hard_gates,
        why_match=list(candidate.why_match),
        gaps=list(candidate.gaps),
        recommended_action=candidate.recommended_action,
    )


def skill_capability_search_response(
    result: SkillSearchResult,
) -> SkillCapabilitySearchResponse:
    """Map application search result to public response schema.

    Args:
        result: Application search result.

    Returns:
        Public search response schema.
    """
    return SkillCapabilitySearchResponse(
        decision=result.decision,
        query=result.query,
        candidates=[
            skill_search_candidate_response(candidate)
            for candidate in result.candidates
        ],
        recommended_action=result.recommended_action,
        gaps=list(result.gaps),
        decision_explanation=result.decision_explanation,
        handoff=result.handoff,
        search_error=result.search_error,
    )
