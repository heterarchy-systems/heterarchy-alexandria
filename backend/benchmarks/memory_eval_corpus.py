"""Strict versioned corpus loader for the Alexandria Memory Evaluation Suite."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import StringConstraints, model_validator

from app.memory.domain.event_enum.context_enums import (
    ContextRecallLifecycleStatus,
    ContextScope,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from benchmarks.memory_eval_contracts import MemoryEvalCase, MemoryEvalQueryClass

MEMORY_EVAL_SCHEMA_VERSION = 1


class MemoryEvalCaseSchema(StrictSchemaModel):
    """Strict JSON truth contract for one durable memory-evaluation case."""

    case_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=120),
        described_field("Stable unique identifier for this memory-evaluation case."),
    ]
    query: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=1000),
        described_field("Search query exercised by this memory-evaluation case."),
    ]
    query_class: Annotated[
        MemoryEvalQueryClass,
        described_field("Memory ability exercised by this evaluation case."),
    ]
    project: Annotated[
        str | None,
        described_field("Optional project routing identity for this evaluation case."),
    ] = None
    include_scopes: Annotated[
        list[ContextScope],
        described_field("Explicit recall scopes used by this evaluation case."),
    ] = schema_list_default()
    include_lifecycle_statuses: Annotated[
        list[ContextRecallLifecycleStatus],
        described_field("Optional lifecycle states visible to this evaluation case."),
    ] = schema_list_default()
    expected_context_ids: Annotated[
        list[str],
        described_field(
            "Accepted current Context identifiers for this evaluation case."
        ),
    ] = schema_list_default()
    expected_titles: Annotated[
        list[str],
        described_field("Accepted current note titles for this evaluation case."),
    ] = schema_list_default()
    forbidden_context_ids: Annotated[
        list[str],
        described_field(
            "Obsolete or incorrect Context identifiers forbidden in recall."
        ),
    ] = schema_list_default()
    forbidden_titles: Annotated[
        list[str],
        described_field("Obsolete or incorrect note titles forbidden in recall."),
    ] = schema_list_default()
    required_graph_relations: Annotated[
        list[str],
        described_field("Graph relation names required for a successful graph case."),
    ] = schema_list_default()
    minimum_graph_distance: Annotated[
        int,
        described_field(
            "Minimum graph evidence distance required for a graph-evaluation case.",
            ge=0,
            le=20,
        ),
    ] = 0
    minimum_expected_matches: Annotated[
        int,
        described_field(
            "Minimum distinct expected memories that must be preserved in results.",
            ge=0,
            le=50,
        ),
    ] = 1
    expected_abstention: Annotated[
        bool,
        described_field(
            "Whether the correct retrieval behavior is to return no memory."
        ),
    ] = False
    rationale: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=2000),
        described_field(
            "Human-reviewed reason this case has the declared truth contract."
        ),
    ]

    @model_validator(mode="after")
    def validate_truth_contract(self) -> MemoryEvalCaseSchema:
        """Reject ambiguous or internally contradictory evaluation truth.

        Returns:
            Validated case schema.

        Raises:
            ValueError: If the case cannot express deterministic benchmark truth.
        """
        expected_values = {*self.expected_context_ids, *self.expected_titles}
        forbidden_values = {*self.forbidden_context_ids, *self.forbidden_titles}
        if expected_values & forbidden_values:
            raise ValueError(
                "expected and forbidden memory identities must not overlap"
            )
        if self.expected_abstention:
            if expected_values:
                raise ValueError("abstention cases must not declare expected memories")
            if self.minimum_expected_matches != 0:
                raise ValueError("abstention cases must set minimum_expected_matches=0")
        elif not expected_values:
            raise ValueError("non-abstention cases must declare expected memories")
        elif self.minimum_expected_matches < 1:
            raise ValueError(
                "non-abstention cases require minimum_expected_matches >= 1"
            )
        elif self.minimum_expected_matches > len(expected_values):
            raise ValueError(
                "minimum_expected_matches exceeds distinct expected memories"
            )
        query_class = MemoryEvalQueryClass(self.query_class)
        if query_class is MemoryEvalQueryClass.CONFLICT_PRESERVATION and (
            self.minimum_expected_matches < 2
        ):
            raise ValueError(
                "conflict-preservation cases must require at least two memories"
            )
        if query_class is MemoryEvalQueryClass.MULTI_HOP_GRAPH and (
            not self.required_graph_relations
        ):
            raise ValueError(
                "multi-hop graph cases must declare required_graph_relations"
            )
        return self

    def to_case(self) -> MemoryEvalCase:
        """Convert strict boundary data into the immutable benchmark domain contract.

        Returns:
            Immutable memory-evaluation case.
        """
        return MemoryEvalCase(
            case_id=self.case_id,
            query=self.query,
            query_class=MemoryEvalQueryClass(self.query_class),
            project=self.project,
            include_scopes=tuple(str(value) for value in self.include_scopes),
            include_lifecycle_statuses=tuple(
                str(value) for value in self.include_lifecycle_statuses
            ),
            expected_context_ids=tuple(self.expected_context_ids),
            expected_titles=tuple(self.expected_titles),
            forbidden_context_ids=tuple(self.forbidden_context_ids),
            forbidden_titles=tuple(self.forbidden_titles),
            required_graph_relations=tuple(self.required_graph_relations),
            minimum_graph_distance=self.minimum_graph_distance,
            minimum_expected_matches=self.minimum_expected_matches,
            expected_abstention=self.expected_abstention,
            rationale=self.rationale,
        )


class MemoryEvalCorpusSchema(StrictSchemaModel):
    """Strict top-level Memory Evaluation Suite corpus contract."""

    schema_version: Annotated[
        Literal[1],
        described_field("Memory Evaluation Suite corpus schema version."),
    ]
    cases: Annotated[
        list[MemoryEvalCaseSchema],
        described_field("Explicit versioned truth cases in this evaluation corpus."),
    ]

    @model_validator(mode="after")
    def validate_unique_cases(self) -> MemoryEvalCorpusSchema:
        """Reject duplicate case identifiers and query texts.

        Returns:
            Corpus with unique stable cases.

        Raises:
            ValueError: If duplicate ids or query texts exist.
        """
        case_ids = [case.case_id for case in self.cases]
        queries = [case.query for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("memory evaluation case_id values must be unique")
        if len(queries) != len(set(queries)):
            raise ValueError("memory evaluation queries must be unique")
        if not self.cases:
            raise ValueError("memory evaluation corpus must contain at least one case")
        return self


def load_memory_eval_cases(path: Path) -> tuple[MemoryEvalCase, ...]:
    """Load one strict JSON-mode Memory Evaluation Suite corpus.

    Args:
        path: Versioned JSON corpus path.

    Returns:
        Immutable evaluation cases in corpus order.

    Raises:
        OSError: If the corpus cannot be read.
        ValueError: If strict JSON validation fails.
    """
    payload = MemoryEvalCorpusSchema.model_validate_json(path.read_bytes())
    return tuple(case.to_case() for case in payload.cases)
