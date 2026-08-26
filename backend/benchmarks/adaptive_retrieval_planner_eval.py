"""Strict golden-corpus evaluation for the deterministic adaptive retrieval planner."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import StringConstraints

from app.memory.application.retrieval.planning.context_adaptive_retrieval_planner import (
    ADAPTIVE_RETRIEVAL_PROFILE_VERSION,
    build_context_retrieval_plan,
)
from app.memory.domain.event_enum.context_enums import (
    ContextRetrievalIntent,
    MemoryFunction,
    RagStrategy,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.types.types_convert_utils import enum_value


class AdaptiveRetrievalPlannerCaseSchema(StrictSchemaModel):
    """One strict planner-intent golden case."""

    case_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=120),
        described_field("Stable planner evaluation case identifier."),
    ]
    query: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=1000),
        described_field("Query classified by the deterministic planner."),
    ]
    expected_intent: Annotated[
        ContextRetrievalIntent,
        described_field("Expected primary deterministic retrieval intent."),
    ]
    expected_strategy: Annotated[
        RagStrategy,
        described_field("Expected fixed execution lane selected by AUTO."),
    ]
    expected_graph_enabled: Annotated[
        bool,
        described_field("Expected graph-enrichment decision."),
    ]
    expected_memory_functions: Annotated[
        list[MemoryFunction],
        described_field("Expected inferred soft functional-memory preferences."),
    ] = schema_list_default()
    expected_temporal_current_preference: Annotated[
        bool,
        described_field("Expected current-state temporal intent flag."),
    ]


class AdaptiveRetrievalPlannerCorpusSchema(StrictSchemaModel):
    """Versioned strict planner-intent golden corpus."""

    schema_version: Annotated[
        Literal[1],
        described_field("Planner corpus schema version."),
    ]
    planner_profile: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=120),
        described_field("Planner profile version evaluated by this corpus."),
    ]
    cases: Annotated[
        list[AdaptiveRetrievalPlannerCaseSchema],
        described_field("Planner-intent golden cases."),
    ]


@dataclass(frozen=True, slots=True, kw_only=True)
class AdaptiveRetrievalPlannerEvaluation:
    """Planner classification and execution-selection regression summary."""

    total_cases: int
    passed_cases: int
    classification_accuracy: float
    failures: tuple[str, ...]


def evaluate_adaptive_retrieval_planner(
    path: Path,
) -> AdaptiveRetrievalPlannerEvaluation:
    """Evaluate the active deterministic profile against a strict golden corpus.

    Args:
        path: Planner corpus JSON path.

    Returns:
        Exact planner regression summary with bounded failure descriptions.

    Raises:
        ValueError: If corpus profile/version or case identities are invalid.
    """
    corpus = AdaptiveRetrievalPlannerCorpusSchema.model_validate_json(path.read_bytes())
    if corpus.planner_profile != ADAPTIVE_RETRIEVAL_PROFILE_VERSION:
        raise ValueError("planner corpus profile does not match active planner profile")
    case_ids = [case.case_id for case in corpus.cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("planner corpus contains duplicate case_id values")
    failures: list[str] = []
    for case in corpus.cases:
        plan = build_context_retrieval_plan(case.query, 5)
        expected_intent = enum_value(
            case.expected_intent, ContextRetrievalIntent, "expected_intent"
        )
        expected_strategy = enum_value(
            case.expected_strategy, RagStrategy, "expected_strategy"
        )
        expected_memory_functions = tuple(
            enum_value(value, MemoryFunction, "expected_memory_functions")
            for value in case.expected_memory_functions
        )
        mismatches: list[str] = []
        if plan.intent is not expected_intent:
            mismatches.append(f"intent={plan.intent.value}")
        if plan.strategy is not expected_strategy:
            mismatches.append(f"strategy={plan.strategy.value}")
        if plan.graph_enabled is not case.expected_graph_enabled:
            mismatches.append(f"graph_enabled={plan.graph_enabled}")
        if plan.preferred_memory_functions != expected_memory_functions:
            mismatches.append("memory_functions")
        if (
            plan.temporal_current_preference
            is not case.expected_temporal_current_preference
        ):
            mismatches.append(
                f"temporal_current_preference={plan.temporal_current_preference}"
            )
        if mismatches:
            failures.append(f"{case.case_id}: " + ", ".join(mismatches))
    total = len(corpus.cases)
    passed = total - len(failures)
    accuracy = 0.0 if total == 0 else round(passed / total, 6)
    return AdaptiveRetrievalPlannerEvaluation(
        total_cases=total,
        passed_cases=passed,
        classification_accuracy=accuracy,
        failures=tuple(failures),
    )
