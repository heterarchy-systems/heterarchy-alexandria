//! Deterministic application-side ranking over typed `PostgreSQL` retrieval candidates.
//!
//! `PostgreSQL` FTS/pgvector query execution, authorization/scope filtering, persistence, and
//! graph enrichment remain outside this module. The kernel only combines caller-ordered,
//! already-filtered candidates.

mod fusion;
mod scoring;

use std::error::Error;
use std::fmt::{Display, Formatter};

use serde::Serialize;

pub use fusion::{
    BestRetrievalIndex, FusedRetrievalIndex, hybrid_candidate_limit, merge_hybrid_candidates,
    merge_hybrid_indices, rank_best_candidates, rank_best_index_values, rank_best_indices,
};
pub use scoring::cosine_similarity;

/// Version of the retrieval candidate/ranking contract.
pub const RETRIEVAL_KERNEL_VERSION: u16 = 1;

/// Number of candidates gathered per requested hybrid result before fusion.
pub const HYBRID_CANDIDATE_MULTIPLIER: usize = 6;
/// Maximum candidates gathered from either `PostgreSQL` retrieval lane.
pub const MAX_HYBRID_CANDIDATE_LIMIT: usize = 50;
/// Standard reciprocal-rank denominator offset used by the Python authority.
pub const RECIPROCAL_RANK_FUSION_CONSTANT: u32 = 60;
/// Minimal semantic-lane preference for otherwise equal lane ranks.
pub const VECTOR_RECIPROCAL_RANK_WEIGHT: f64 = 1.01;

const MAX_LANE_CANDIDATES: usize = 1_000_000;
const MAX_CONTEXT_ID_BYTES: usize = 4_096;
const MAX_REASON_BYTES: usize = 64 * 1_024;

/// Candidate lane from which one representative match originated.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RetrievalLane {
    /// `PostgreSQL` full-text-search lane.
    Fts,
    /// `PostgreSQL` vector-similarity lane.
    Vector,
}

/// One caller-ordered candidate whose scope/lifecycle policy was already applied.
#[derive(Debug, Clone, PartialEq)]
pub struct RetrievalCandidate {
    /// Stable canonical context identity used for cross-chunk deduplication.
    pub context_id: String,
    /// Original lane score. Fusion does not reinterpret this score.
    pub score: f64,
    /// Optional `PostgreSQL` FTS score evidence.
    pub fts_score: Option<f64>,
    /// Optional pgvector score evidence.
    pub vector_score: Option<f64>,
    /// Caller-owned explanation retained for one-lane representatives.
    pub why_retrieved: String,
}

/// Compact context/score input for best-per-context ranking across the Python boundary.
#[derive(Debug, Clone, PartialEq)]
pub struct RetrievalScoreInput {
    /// Stable canonical context identity.
    pub context_id: String,
    /// Candidate score used for ordering.
    pub score: f64,
}

impl RetrievalScoreInput {
    /// Construct one validated compact ranking input.
    ///
    /// # Errors
    ///
    /// Returns a typed input error for an invalid identity or non-finite score.
    pub fn new(context_id: String, score: f64) -> Result<Self, RetrievalKernelError> {
        validate_context_id(&context_id)?;
        validate_finite("score", score)?;
        Ok(Self { context_id, score })
    }
}

impl RetrievalCandidate {
    /// Construct one finite bounded candidate.
    ///
    /// # Errors
    ///
    /// Returns a typed input error for blank/oversized identities, oversized reasons, null
    /// bytes, or non-finite numeric values.
    pub fn new(
        context_id: String,
        score: f64,
        fts_score: Option<f64>,
        vector_score: Option<f64>,
        why_retrieved: String,
    ) -> Result<Self, RetrievalKernelError> {
        validate_context_id(&context_id)?;
        validate_text("why_retrieved", &why_retrieved, MAX_REASON_BYTES, true)?;
        validate_finite("score", score)?;
        if let Some(value) = fts_score {
            validate_finite("fts_score", value)?;
        }
        if let Some(value) = vector_score {
            validate_finite("vector_score", value)?;
        }
        Ok(Self {
            context_id,
            score,
            fts_score,
            vector_score,
            why_retrieved,
        })
    }
}

/// Explicit representative position in the caller-provided retrieval lanes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct CandidateRepresentative {
    /// Source lane.
    pub lane: RetrievalLane,
    /// Zero-based position in that source lane, including skipped duplicate rows.
    pub lane_index: usize,
}

/// One context-level result produced by best-lane reciprocal-rank fusion.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct FusedRetrievalCandidate {
    /// Canonical context identity.
    pub context_id: String,
    /// Representative lane and lane-local input index.
    pub representative: CandidateRepresentative,
    /// Best reciprocal-rank contribution across lanes, never the sum of both lanes.
    pub score: f64,
    /// Optional FTS score evidence from the first unique FTS candidate.
    pub fts_score: Option<f64>,
    /// Optional vector score evidence from the first unique vector candidate.
    pub vector_score: Option<f64>,
    /// Fused or representative retrieval explanation.
    pub why_retrieved: String,
}

/// One best-chunk-per-context result from a single candidate sequence.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct BestRetrievalCandidate {
    /// Canonical context identity.
    pub context_id: String,
    /// Zero-based candidate index selected as the representative.
    pub candidate_index: usize,
    /// Original selected candidate score.
    pub score: f64,
}

/// Stable typed failure category for retrieval-kernel input validation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RetrievalKernelErrorCode {
    /// Invalid candidate identity, explanation, limit, or numeric input.
    InvalidInput,
    /// Caller-provided candidate cardinality exceeds the safety bound.
    CandidateLimitExceeded,
}

/// Structured non-secret retrieval-kernel failure.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RetrievalKernelError {
    /// Stable machine-readable category.
    pub code: RetrievalKernelErrorCode,
    /// Sanitized diagnostic message.
    pub message: String,
    /// Optional lane associated with a candidate failure.
    pub lane: Option<RetrievalLane>,
    /// Optional zero-based lane-local candidate index.
    pub candidate_index: Option<usize>,
}

impl RetrievalKernelError {
    fn invalid_input(message: impl Into<String>) -> Self {
        Self {
            code: RetrievalKernelErrorCode::InvalidInput,
            message: message.into(),
            lane: None,
            candidate_index: None,
        }
    }

    fn candidate_limit(lane: RetrievalLane, candidate_count: usize) -> Self {
        Self {
            code: RetrievalKernelErrorCode::CandidateLimitExceeded,
            message: format!(
                "{lane:?} candidate count {candidate_count} exceeds the {MAX_LANE_CANDIDATES} item limit"
            ),
            lane: Some(lane),
            candidate_index: None,
        }
    }
}

impl Display for RetrievalKernelError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for RetrievalKernelError {}

fn validate_lane_count(
    lane: RetrievalLane,
    candidate_count: usize,
) -> Result<(), RetrievalKernelError> {
    if candidate_count > MAX_LANE_CANDIDATES {
        return Err(RetrievalKernelError::candidate_limit(lane, candidate_count));
    }
    Ok(())
}

pub(crate) fn validate_context_id(context_id: &str) -> Result<(), RetrievalKernelError> {
    validate_text("context_id", context_id, MAX_CONTEXT_ID_BYTES, false)
}

fn validate_text(
    field_name: &str,
    value: &str,
    max_bytes: usize,
    allow_blank: bool,
) -> Result<(), RetrievalKernelError> {
    if !allow_blank && value.trim().is_empty() {
        return Err(RetrievalKernelError::invalid_input(format!(
            "{field_name} must not be blank"
        )));
    }
    if value.len() > max_bytes {
        return Err(RetrievalKernelError::invalid_input(format!(
            "{field_name} exceeds the {max_bytes} byte limit"
        )));
    }
    if value.contains('\0') {
        return Err(RetrievalKernelError::invalid_input(format!(
            "{field_name} must not contain a null byte"
        )));
    }
    Ok(())
}

fn validate_finite(field_name: &str, value: f64) -> Result<(), RetrievalKernelError> {
    if !value.is_finite() {
        return Err(RetrievalKernelError::invalid_input(format!(
            "{field_name} must be finite"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        RetrievalCandidate, RetrievalLane, cosine_similarity, hybrid_candidate_limit,
        merge_hybrid_candidates, rank_best_candidates,
    };

    fn candidate(
        context_id: &str,
        score: f64,
        fts_score: Option<f64>,
        vector_score: Option<f64>,
        why_retrieved: &str,
    ) -> RetrievalCandidate {
        match RetrievalCandidate::new(
            context_id.to_owned(),
            score,
            fts_score,
            vector_score,
            why_retrieved.to_owned(),
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("test candidate must be valid: {error}"),
        }
    }

    #[test]
    fn candidate_limit_matches_the_bounded_python_policy() {
        assert_eq!(hybrid_candidate_limit(0), 0);
        assert_eq!(hybrid_candidate_limit(1), 6);
        assert_eq!(hybrid_candidate_limit(5), 30);
        assert_eq!(hybrid_candidate_limit(20), 50);
        assert_eq!(hybrid_candidate_limit(usize::MAX), 50);
    }

    #[test]
    fn best_lane_fusion_prefers_vector_without_double_counting() {
        let fused = match merge_hybrid_candidates(
            &[candidate("noise", 0.1, Some(0.1), None, "lexical")],
            &[
                candidate("semantic", 0.99, None, Some(0.99), "semantic"),
                candidate("noise", 0.95, None, Some(0.95), "vector noise"),
            ],
            2,
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid fusion failed: {error}"),
        };
        assert_eq!(fused[0].context_id, "semantic");
        assert_eq!(fused[0].representative.lane, RetrievalLane::Vector);
        assert_eq!(fused[1].context_id, "noise");
        assert_eq!(fused[1].representative.lane, RetrievalLane::Fts);
        assert!(fused[1].score < fused[0].score);
    }

    #[test]
    fn duplicate_lane_rows_consume_rank_but_keep_first_evidence() {
        let fused = match merge_hybrid_candidates(
            &[
                candidate("alpha", 0.8, Some(0.8), None, "first"),
                candidate("alpha", 0.99, Some(0.99), None, "duplicate"),
                candidate("beta", 0.7, Some(0.7), None, "third"),
            ],
            &[],
            5,
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid fusion failed: {error}"),
        };
        assert_eq!(fused[0].why_retrieved, "first");
        assert_eq!(fused[1].representative.lane_index, 2);
    }

    #[test]
    fn best_match_dedup_keeps_first_equal_score_and_stable_ties() {
        let ranked = match rank_best_candidates(
            &[
                candidate("beta", 0.8, Some(0.8), None, "beta"),
                candidate("alpha", 0.8, Some(0.8), None, "alpha first"),
                candidate("alpha", 0.8, Some(0.8), None, "alpha second"),
            ],
            5,
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid best-match ranking failed: {error}"),
        };
        assert_eq!(ranked[0].context_id, "beta");
        assert_eq!(ranked[1].candidate_index, 1);
    }

    #[test]
    fn cosine_similarity_matches_python_vector_edges() {
        assert_eq!(
            cosine_similarity(&[1.0, 0.0], &[1.0, 0.0]).to_bits(),
            1.0_f64.to_bits()
        );
        assert_eq!(
            cosine_similarity(&[1.0, 0.0], &[0.0, 1.0]).to_bits(),
            0.0_f64.to_bits()
        );
        assert_eq!(
            cosine_similarity(&[0.0, 0.0], &[1.0, 1.0]).to_bits(),
            0.0_f64.to_bits()
        );
        assert_eq!(
            cosine_similarity(&[1.0], &[1.0, 0.0]).to_bits(),
            0.0_f64.to_bits()
        );
    }
}
