//! Lower-copy `PyO3` boundary for retrieval ranking.
//!
//! Python retains heavyweight `ContextSearchMatch` objects and sends only IDs/scores. Rust returns
//! source indices and fused scores so the Python adapter can materialize the existing domain DTOs.

use heterarchy_alexandria_core::retrieval_kernel::{
    RetrievalFusionTrace, RetrievalLane, hybrid_candidate_limit, merge_hybrid_indices,
    merge_hybrid_indices_with_trace, rank_best_index_values,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;

pub(crate) type CompactFusionOutput = (String, usize, Option<usize>, Option<usize>, f64);
pub(crate) type CompactFusionTraceOutput = (
    usize,
    usize,
    usize,
    usize,
    usize,
    usize,
    usize,
    usize,
    usize,
    usize,
    usize,
);

#[pyfunction]
pub(crate) fn retrieval_hybrid_candidate_limit(limit: usize) -> usize {
    hybrid_candidate_limit(limit)
}

#[pyfunction]
pub(crate) fn retrieval_merge_hybrid_indices(
    python: Python<'_>,
    fts_context_ids: Vec<PyBackedStr>,
    vector_context_ids: Vec<PyBackedStr>,
    limit: usize,
) -> PyResult<Vec<CompactFusionOutput>> {
    python
        .detach(move || {
            merge_hybrid_indices(&fts_context_ids, &vector_context_ids, limit).map(|results| {
                results
                    .into_iter()
                    .map(|item| {
                        (
                            lane_name(item.representative.lane).to_owned(),
                            item.representative.lane_index,
                            item.fts_index,
                            item.vector_index,
                            item.score,
                        )
                    })
                    .collect()
            })
        })
        .map_err(|error| {
            PyValueError::new_err(format!("NATIVE_RETRIEVAL_KERNEL_RESULT_ERROR: {error}"))
        })
}

#[pyfunction]
pub(crate) fn retrieval_merge_hybrid_indices_with_trace(
    python: Python<'_>,
    fts_context_ids: Vec<PyBackedStr>,
    vector_context_ids: Vec<PyBackedStr>,
    limit: usize,
) -> PyResult<(Vec<CompactFusionOutput>, CompactFusionTraceOutput)> {
    python
        .detach(move || {
            merge_hybrid_indices_with_trace(&fts_context_ids, &vector_context_ids, limit).map(
                |(results, trace)| {
                    let outputs = results
                        .into_iter()
                        .map(|item| {
                            (
                                lane_name(item.representative.lane).to_owned(),
                                item.representative.lane_index,
                                item.fts_index,
                                item.vector_index,
                                item.score,
                            )
                        })
                        .collect();
                    (outputs, compact_trace(trace))
                },
            )
        })
        .map_err(|error| {
            PyValueError::new_err(format!("NATIVE_RETRIEVAL_KERNEL_RESULT_ERROR: {error}"))
        })
}

#[pyfunction]
pub(crate) fn retrieval_rank_best_indices(
    python: Python<'_>,
    candidates: Vec<(PyBackedStr, f64)>,
    limit: usize,
) -> PyResult<Vec<(usize, f64)>> {
    let (context_ids, scores): (Vec<_>, Vec<_>) = candidates.into_iter().unzip();
    python
        .detach(move || {
            rank_best_index_values(&context_ids, &scores, limit).map(|results| {
                results
                    .into_iter()
                    .map(|item| (item.candidate_index, item.score))
                    .collect()
            })
        })
        .map_err(|error| {
            PyValueError::new_err(format!("NATIVE_RETRIEVAL_KERNEL_RESULT_ERROR: {error}"))
        })
}

const fn compact_trace(trace: RetrievalFusionTrace) -> CompactFusionTraceOutput {
    (
        trace.fts_input_count,
        trace.vector_input_count,
        trace.fts_unique_count,
        trace.vector_unique_count,
        trace.fts_duplicate_count,
        trace.vector_duplicate_count,
        trace.fused_candidate_count,
        trace.cross_lane_count,
        trace.returned_count,
        trace.representative_fts_count,
        trace.representative_vector_count,
    )
}

const fn lane_name(lane: RetrievalLane) -> &'static str {
    match lane {
        RetrievalLane::Fts => "fts",
        RetrievalLane::Vector => "vector",
    }
}

#[cfg(test)]
mod tests {
    use super::{compact_trace, lane_name};
    use heterarchy_alexandria_core::retrieval_kernel::{RetrievalFusionTrace, RetrievalLane};

    #[test]
    fn compact_lane_names_are_stable() {
        assert_eq!(lane_name(RetrievalLane::Fts), "fts");
        assert_eq!(lane_name(RetrievalLane::Vector), "vector");
    }

    #[test]
    fn compact_trace_field_order_is_stable() {
        let trace = RetrievalFusionTrace {
            fts_input_count: 1,
            vector_input_count: 2,
            fts_unique_count: 3,
            vector_unique_count: 4,
            fts_duplicate_count: 5,
            vector_duplicate_count: 6,
            fused_candidate_count: 7,
            cross_lane_count: 8,
            returned_count: 9,
            representative_fts_count: 10,
            representative_vector_count: 11,
        };
        assert_eq!(compact_trace(trace), (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11));
    }
}
