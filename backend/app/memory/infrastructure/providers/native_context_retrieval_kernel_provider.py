"""Native Rust adapter for deterministic Context retrieval ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.repositories.contexts.context_retrieval_kernel_provider import (
    ContextRetrievalFusionTrace,
    ContextRetrievalMergeTraceResult,
    IContextRetrievalKernelProvider,
)

_FUSED_RETRIEVAL_REASON = (
    "Context ranked across lexical and semantic vector evidence "
    "using best-lane reciprocal-rank fusion."
)

type NativeFusionRow = tuple[str, int, int | None, int | None, float]
type NativeFusionTraceRow = tuple[int, int, int, int, int, int, int, int, int, int, int]
type NativeFusionTraceResult = tuple[list[NativeFusionRow], NativeFusionTraceRow]
type NativeBestRow = tuple[int, float]


# protocol-contract: structural-seam
class NativeRetrievalKernelModule(Protocol):
    """Minimal native-extension surface required by the retrieval kernel adapter."""

    def compute_contract_version(self) -> int:
        """Return the coarse Python/Rust compute contract version.

        Returns:
            Native compute contract version.
        """

    def retrieval_hybrid_candidate_limit(self, limit: int) -> int:
        """Return the native Hybrid lane candidate bound.

        Args:
            limit: Requested final result count.

        Returns:
            Bounded per-lane candidate count.
        """

    def retrieval_merge_hybrid_indices(
        self,
        fts_context_ids: list[str],
        vector_context_ids: list[str],
        limit: int,
    ) -> list[NativeFusionRow]:
        """Return compact Rust fusion rows for ordered candidate lanes.

        Args:
            fts_context_ids: Ordered FTS Context identities.
            vector_context_ids: Ordered vector Context identities.
            limit: Maximum final result count.

        Returns:
            Compact native fusion rows referencing source lane indices.
        """

    def retrieval_merge_hybrid_indices_with_trace(
        self,
        fts_context_ids: list[str],
        vector_context_ids: list[str],
        limit: int,
    ) -> NativeFusionTraceResult:
        """Return compact fusion rows and deterministic fusion diagnostics.

        Args:
            fts_context_ids: Ordered FTS Context identities.
            vector_context_ids: Ordered vector Context identities.
            limit: Maximum final result count.

        Returns:
            Compact native fusion rows and trace counters.
        """

    def retrieval_rank_best_indices(
        self,
        candidates: list[tuple[str, float]],
        limit: int,
    ) -> list[NativeBestRow]:
        """Return compact best-per-Context rows.

        Args:
            candidates: Ordered Context identity and score pairs.
            limit: Maximum returned Context count.

        Returns:
            Candidate index and score rows in native ranking order.
        """


@dataclass(frozen=True, slots=True)
class NativeContextRetrievalKernelProvider(IContextRetrievalKernelProvider):
    """Map compact Rust retrieval output back into existing Python read models.

    The native module is required and injected by composition; this adapter exposes no
    alternate production compute path.
    """

    native_module: NativeRetrievalKernelModule

    @property
    def authority(self) -> str:
        """Return the active retrieval compute authority.

        Returns:
            ``rust`` for the native retrieval kernel adapter.
        """
        return "rust"

    def hybrid_candidate_limit(self, limit: int) -> int:
        """Return the native per-lane candidate bound.

        Args:
            limit: Requested final result count.

        Returns:
            Bounded candidate count used before Hybrid fusion.
        """
        result = self.native_module.retrieval_hybrid_candidate_limit(limit)
        if result < limit:
            raise ValueError(
                "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: candidate limit is below "
                "the requested final limit"
            )
        return result

    def merge(
        self,
        fts_matches: list[ContextSearchMatch],
        vector_matches: list[ContextSearchMatch],
        limit: int,
    ) -> list[ContextSearchMatch]:
        """Return Rust-ranked hybrid matches while retaining heavyweight Python DTOs.

        Args:
            fts_matches: Already-filtered FTS lane in source rank order.
            vector_matches: Already-filtered vector lane in source rank order.
            limit: Maximum final result count.

        Returns:
            Hybrid-ranked Context matches.

        Raises:
            ValueError: If native output violates the compact boundary contract.
        """
        rows = self.native_module.retrieval_merge_hybrid_indices(
            [match.context.id for match in fts_matches],
            [match.context.id for match in vector_matches],
            limit,
        )
        return [
            _materialize_fusion_row(
                row,
                fts_matches=fts_matches,
                vector_matches=vector_matches,
            )
            for row in rows
        ]

    def merge_with_trace(
        self,
        fts_matches: list[ContextSearchMatch],
        vector_matches: list[ContextSearchMatch],
        limit: int,
    ) -> ContextRetrievalMergeTraceResult:
        """Return Rust-ranked hybrid matches and native fusion diagnostics.

        Args:
            fts_matches: Already-filtered FTS lane in source rank order.
            vector_matches: Already-filtered vector lane in source rank order.
            limit: Maximum final result count.

        Returns:
            Hybrid-ranked matches paired with strict native fusion diagnostics.

        Raises:
            ValueError: If native output violates the compact trace boundary contract.
        """
        rows, trace_row = self.native_module.retrieval_merge_hybrid_indices_with_trace(
            [match.context.id for match in fts_matches],
            [match.context.id for match in vector_matches],
            limit,
        )
        matches = tuple(
            _materialize_fusion_row(
                row,
                fts_matches=fts_matches,
                vector_matches=vector_matches,
            )
            for row in rows
        )
        trace = _decode_fusion_trace(
            trace_row,
            fts_input_count=len(fts_matches),
            vector_input_count=len(vector_matches),
            returned_count=len(matches),
            limit=limit,
        )
        return ContextRetrievalMergeTraceResult(matches=matches, trace=trace)

    def rank_best(
        self,
        matches: list[ContextSearchMatch],
        limit: int,
    ) -> list[ContextSearchMatch]:
        """Return native best-per-Context ranking without crossing heavyweight DTOs.

        Args:
            matches: Ordered candidate matches.
            limit: Maximum returned Context count.

        Returns:
            Best match per Context in native ranking order.

        Raises:
            ValueError: If native output references an invalid candidate or score.
        """
        rows = self.native_module.retrieval_rank_best_indices(
            [(match.context.id, match.score) for match in matches],
            limit,
        )
        ranked: list[ContextSearchMatch] = []
        seen_indices: set[int] = set()
        for index, score in rows:
            if index in seen_indices:
                raise ValueError(
                    "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: duplicate best-match index"
                )
            seen_indices.add(index)
            match = _indexed_match(matches, index, lane_name="candidate")
            if _finite_score(score) != match.score:
                raise ValueError(
                    "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: best-match score drift"
                )
            ranked.append(match)
        return ranked


def _decode_fusion_trace(
    row: NativeFusionTraceRow,
    fts_input_count: int,
    vector_input_count: int,
    returned_count: int,
    limit: int,
) -> ContextRetrievalFusionTrace:
    """Decode and validate the compact native fusion trace tuple.

    Args:
        row: Native trace counters in the stable compact field order.
        fts_input_count: Python-observed FTS candidate count.
        vector_input_count: Python-observed vector candidate count.
        returned_count: Number of materialized native fusion rows.
        limit: Requested final result count.

    Returns:
        Strict typed fusion trace.

    Raises:
        ValueError: If native trace counters violate boundary invariants.
    """
    if len(row) != 11:
        raise ValueError(
            "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: invalid fusion trace width"
        )
    values = tuple(_non_negative_int(value, field_name="fusion trace") for value in row)
    (
        native_fts_input,
        native_vector_input,
        fts_unique,
        vector_unique,
        fts_duplicates,
        vector_duplicates,
        fused_candidates,
        cross_lane,
        native_returned,
        representative_fts,
        representative_vector,
    ) = values
    if native_fts_input != fts_input_count or native_vector_input != vector_input_count:
        raise ValueError(
            "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: fusion trace input count drift"
        )
    if fts_unique + fts_duplicates != native_fts_input:
        raise ValueError(
            "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: invalid FTS trace counts"
        )
    if vector_unique + vector_duplicates != native_vector_input:
        raise ValueError(
            "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: invalid vector trace counts"
        )
    if fused_candidates > fts_unique + vector_unique or cross_lane > min(
        fts_unique, vector_unique
    ):
        raise ValueError(
            "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: invalid fusion trace cardinality"
        )
    if native_returned != returned_count or native_returned > limit:
        raise ValueError(
            "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: fusion trace returned count drift"
        )
    if representative_fts + representative_vector != native_returned:
        raise ValueError(
            "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: invalid representative trace counts"
        )
    return ContextRetrievalFusionTrace(
        fts_input_count=native_fts_input,
        vector_input_count=native_vector_input,
        fts_unique_count=fts_unique,
        vector_unique_count=vector_unique,
        fts_duplicate_count=fts_duplicates,
        vector_duplicate_count=vector_duplicates,
        fused_candidate_count=fused_candidates,
        cross_lane_count=cross_lane,
        returned_count=native_returned,
        representative_fts_count=representative_fts,
        representative_vector_count=representative_vector,
    )


def _non_negative_int(value: int, field_name: str) -> int:
    """Validate one strict non-negative integer from the native trace boundary.

    Args:
        value: Native integer value to validate.
        field_name: Diagnostic field label used in validation failures.

    Returns:
        Validated non-negative integer.

    Raises:
        ValueError: If the value is boolean, non-integer, or negative.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: invalid non-negative {field_name}"
        )
    return value


def _materialize_fusion_row(
    row: NativeFusionRow,
    fts_matches: list[ContextSearchMatch],
    vector_matches: list[ContextSearchMatch],
) -> ContextSearchMatch:
    """Execute materialize fusion row.

    Args:
        row: Row used by this operation.
        fts_matches: Fts matches used by this operation.
        vector_matches: Vector matches used by this operation.

    Returns:
        ContextSearchMatch result produced by materialize fusion row.
    """
    lane, representative_index, fts_index, vector_index, score = row
    representative = _representative_match(
        lane,
        representative_index,
        fts_matches=fts_matches,
        vector_matches=vector_matches,
    )
    fts_score = _lane_score(fts_matches, fts_index, lane_name="fts")
    vector_score = _lane_score(vector_matches, vector_index, lane_name="vector")
    why_retrieved = representative.why_retrieved
    if fts_score is not None and vector_score is not None:
        why_retrieved = _FUSED_RETRIEVAL_REASON
    return ContextSearchMatch(
        context=representative.context,
        chunk=representative.chunk,
        score=_finite_score(score),
        fts_score=fts_score,
        vector_score=vector_score,
        why_retrieved=why_retrieved,
    )


def _representative_match(
    lane: str,
    index: int,
    fts_matches: list[ContextSearchMatch],
    vector_matches: list[ContextSearchMatch],
) -> ContextSearchMatch:
    """Execute representative match.

    Args:
        lane: Lane used by this operation.
        index: Index used by this operation.
        fts_matches: Fts matches used by this operation.
        vector_matches: Vector matches used by this operation.

    Returns:
        ContextSearchMatch result produced by representative match.
    """
    if lane == "fts":
        return _indexed_match(fts_matches, index, lane_name="fts")
    if lane == "vector":
        return _indexed_match(vector_matches, index, lane_name="vector")
    raise ValueError(f"NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: unsupported lane {lane!r}")


def _lane_score(
    matches: list[ContextSearchMatch],
    index: int | None,
    lane_name: str,
) -> float | None:
    """Execute lane score.

    Args:
        matches: Matches used by this operation.
        index: Index used by this operation.
        lane_name: Lane name used by this operation.

    Returns:
        float | None result produced by lane score.
    """
    if index is None:
        return None
    match = _indexed_match(matches, index, lane_name=lane_name)
    score = match.fts_score if lane_name == "fts" else match.vector_score
    if score is None:
        raise ValueError(
            "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: native lane index points to "
            f"a {lane_name} match without its lane score"
        )
    return score


def _indexed_match(
    matches: list[ContextSearchMatch],
    index: int,
    lane_name: str,
) -> ContextSearchMatch:
    """Execute indexed match.

    Args:
        matches: Matches used by this operation.
        index: Index used by this operation.
        lane_name: Lane name used by this operation.

    Returns:
        ContextSearchMatch result produced by indexed match.
    """
    if index < 0 or index >= len(matches):
        raise ValueError(
            "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: "
            f"{lane_name} index {index} is outside 0..{len(matches)}"
        )
    return matches[index]


def _finite_score(value: float) -> float:
    """Execute finite score.

    Args:
        value: Value being processed.

    Returns:
        float result produced by finite score.
    """
    if not isinstance(value, float) or not (float("-inf") < value < float("inf")):
        raise ValueError(
            "NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: fused score must be finite"
        )
    return value
