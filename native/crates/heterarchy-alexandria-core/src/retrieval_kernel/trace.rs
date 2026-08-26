use serde::Serialize;

/// Deterministic diagnostics emitted by one hybrid retrieval fusion execution.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct RetrievalFusionTrace {
    /// Number of FTS candidate rows presented to the kernel.
    pub fts_input_count: usize,
    /// Number of vector candidate rows presented to the kernel.
    pub vector_input_count: usize,
    /// Number of distinct Context identities in the FTS lane.
    pub fts_unique_count: usize,
    /// Number of distinct Context identities in the vector lane.
    pub vector_unique_count: usize,
    /// Number of duplicate FTS rows ignored after consuming rank position.
    pub fts_duplicate_count: usize,
    /// Number of duplicate vector rows ignored after consuming rank position.
    pub vector_duplicate_count: usize,
    /// Number of distinct Context identities across both lanes before top-k truncation.
    pub fused_candidate_count: usize,
    /// Number of Context identities carrying evidence from both lanes.
    pub cross_lane_count: usize,
    /// Number of fused results returned after top-k truncation.
    pub returned_count: usize,
    /// Number of returned results represented by the FTS lane.
    pub representative_fts_count: usize,
    /// Number of returned results represented by the vector lane.
    pub representative_vector_count: usize,
}
