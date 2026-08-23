//! Lower-copy `PyO3` boundary for retrieval ranking.
//!
//! Python retains heavyweight `ContextSearchMatch` objects and sends only IDs/scores. Rust returns
//! source indices and fused scores so the Python adapter can materialize the existing domain DTOs.

use heterarchy_alexandria_core::retrieval_kernel::{
    RetrievalLane, hybrid_candidate_limit, merge_hybrid_indices, rank_best_index_values,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;

pub(crate) type CompactFusionOutput = (String, usize, Option<usize>, Option<usize>, f64);

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

const fn lane_name(lane: RetrievalLane) -> &'static str {
    match lane {
        RetrievalLane::Fts => "fts",
        RetrievalLane::Vector => "vector",
    }
}

#[cfg(test)]
mod tests {
    use super::lane_name;
    use heterarchy_alexandria_core::retrieval_kernel::RetrievalLane;

    #[test]
    fn compact_lane_names_are_stable() {
        assert_eq!(lane_name(RetrievalLane::Fts), "fts");
        assert_eq!(lane_name(RetrievalLane::Vector), "vector");
    }
}
