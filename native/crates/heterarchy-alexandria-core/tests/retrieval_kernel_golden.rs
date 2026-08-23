//! Live-Python golden parity for deterministic retrieval candidate compute.

use heterarchy_alexandria_core::retrieval_kernel::{
    RetrievalCandidate, cosine_similarity, hybrid_candidate_limit, merge_hybrid_candidates,
    rank_best_candidates,
};
use serde::Deserialize;
use serde_json::Value;

const GOLDEN_CORPUS: &str = include_str!("../../../corpora/retrieval_kernel/v1/cases.json");

#[derive(Debug, Deserialize)]
struct GoldenCorpus {
    schema_version: u16,
    feature: String,
    candidate_limit_cases: Vec<CandidateLimitCase>,
    fusion_cases: Vec<FusionCase>,
    best_match_cases: Vec<BestMatchCase>,
    cosine_cases: Vec<CosineCase>,
}

#[derive(Debug, Deserialize)]
struct CandidateLimitCase {
    limit: usize,
    expected: usize,
}

#[derive(Debug, Deserialize)]
struct FusionCase {
    case_id: String,
    limit: usize,
    fts_matches: Vec<CandidateWire>,
    vector_matches: Vec<CandidateWire>,
    expected: Value,
}

#[derive(Debug, Deserialize)]
struct BestMatchCase {
    case_id: String,
    limit: usize,
    matches: Vec<CandidateWire>,
    expected: Value,
}

#[derive(Debug, Deserialize)]
struct CosineCase {
    case_id: String,
    left: Vec<f64>,
    right: Vec<f64>,
    expected: f64,
}

#[derive(Debug, Deserialize)]
struct CandidateWire {
    context_id: String,
    score: f64,
    fts_score: Option<f64>,
    vector_score: Option<f64>,
    why_retrieved: String,
}

#[test]
fn retrieval_kernel_matches_the_frozen_python_baseline() {
    let corpus: GoldenCorpus = match serde_json::from_str(GOLDEN_CORPUS) {
        Ok(value) => value,
        Err(error) => unreachable!("retrieval kernel corpus must be valid JSON: {error}"),
    };
    assert_eq!(corpus.schema_version, 1);
    assert_eq!(corpus.feature, "retrieval_kernel");

    for case in corpus.candidate_limit_cases {
        assert_eq!(hybrid_candidate_limit(case.limit), case.expected);
    }
    for case in corpus.fusion_cases {
        let fts = candidates_from_wire(case.fts_matches, &case.case_id);
        let vector = candidates_from_wire(case.vector_matches, &case.case_id);
        let actual = match merge_hybrid_candidates(&fts, &vector, case.limit) {
            Ok(value) => value,
            Err(error) => unreachable!("{} fusion failed: {error}", case.case_id),
        };
        let actual = match serde_json::to_value(actual) {
            Ok(value) => value,
            Err(error) => unreachable!("{} fusion must serialize: {error}", case.case_id),
        };
        assert_eq!(actual, case.expected, "{} fusion parity", case.case_id);
    }
    for case in corpus.best_match_cases {
        let candidates = candidates_from_wire(case.matches, &case.case_id);
        let actual = match rank_best_candidates(&candidates, case.limit) {
            Ok(value) => value,
            Err(error) => unreachable!("{} best-match ranking failed: {error}", case.case_id),
        };
        let actual = match serde_json::to_value(actual) {
            Ok(value) => value,
            Err(error) => {
                unreachable!("{} best-match result must serialize: {error}", case.case_id)
            }
        };
        assert_eq!(actual, case.expected, "{} best-match parity", case.case_id);
    }
    for case in corpus.cosine_cases {
        let actual = cosine_similarity(&case.left, &case.right);
        assert_eq!(
            actual.to_bits(),
            case.expected.to_bits(),
            "{} cosine parity",
            case.case_id
        );
    }
}

fn candidates_from_wire(values: Vec<CandidateWire>, case_id: &str) -> Vec<RetrievalCandidate> {
    values
        .into_iter()
        .map(|value| {
            match RetrievalCandidate::new(
                value.context_id,
                value.score,
                value.fts_score,
                value.vector_score,
                value.why_retrieved,
            ) {
                Ok(candidate) => candidate,
                Err(error) => unreachable!("{case_id} candidate must be valid: {error}"),
            }
        })
        .collect()
}
