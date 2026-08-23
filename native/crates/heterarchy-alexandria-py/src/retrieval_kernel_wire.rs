//! Strict JSON wire conversion for deterministic retrieval candidate ranking.

use heterarchy_alexandria_core::retrieval_kernel::{
    RETRIEVAL_KERNEL_VERSION, RetrievalCandidate, cosine_similarity, hybrid_candidate_limit,
    merge_hybrid_candidates, rank_best_candidates,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RetrievalKernelEnvelopeWire {
    contract_version: u16,
    retrieval_version: u16,
    request: RetrievalKernelRequestWire,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
enum RetrievalKernelRequestWire {
    HybridCandidateLimit {
        limit: usize,
    },
    MergeHybrid {
        limit: usize,
        fts_candidates: Vec<RetrievalCandidateWire>,
        vector_candidates: Vec<RetrievalCandidateWire>,
    },
    RankBest {
        limit: usize,
        candidates: Vec<RetrievalCandidateWire>,
    },
    CosineSimilarity {
        left: Vec<f64>,
        right: Vec<f64>,
    },
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RetrievalCandidateWire {
    context_id: String,
    score: f64,
    fts_score: Option<f64>,
    vector_score: Option<f64>,
    why_retrieved: String,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
enum RetrievalOperationName {
    HybridCandidateLimit,
    MergeHybrid,
    RankBest,
    CosineSimilarity,
}

#[derive(Debug, Serialize)]
struct RetrievalKernelResponse<ResultValue> {
    contract_version: u16,
    retrieval_version: u16,
    operation: RetrievalOperationName,
    result: ResultValue,
}

pub(crate) fn compute_retrieval_kernel_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: RetrievalKernelEnvelopeWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_RETRIEVAL_KERNEL_INPUT_ERROR: {error}"))?;
    validate_versions(wire.contract_version, wire.retrieval_version)?;
    match wire.request {
        RetrievalKernelRequestWire::HybridCandidateLimit { limit } => encode_response(
            RetrievalOperationName::HybridCandidateLimit,
            hybrid_candidate_limit(limit),
        ),
        RetrievalKernelRequestWire::MergeHybrid {
            limit,
            fts_candidates,
            vector_candidates,
        } => {
            let fts_candidates = candidates_from_wire(fts_candidates)?;
            let vector_candidates = candidates_from_wire(vector_candidates)?;
            let result = merge_hybrid_candidates(&fts_candidates, &vector_candidates, limit)
                .map_err(|error| format!("NATIVE_RETRIEVAL_KERNEL_RESULT_ERROR: {error}"))?;
            encode_response(RetrievalOperationName::MergeHybrid, result)
        }
        RetrievalKernelRequestWire::RankBest { limit, candidates } => {
            let candidates = candidates_from_wire(candidates)?;
            let result = rank_best_candidates(&candidates, limit)
                .map_err(|error| format!("NATIVE_RETRIEVAL_KERNEL_RESULT_ERROR: {error}"))?;
            encode_response(RetrievalOperationName::RankBest, result)
        }
        RetrievalKernelRequestWire::CosineSimilarity { left, right } => encode_response(
            RetrievalOperationName::CosineSimilarity,
            cosine_similarity(&left, &right),
        ),
    }
}

fn validate_versions(contract_version: u16, retrieval_version: u16) -> Result<(), String> {
    crate::validate_contract_version(contract_version, "NATIVE_RETRIEVAL_KERNEL_CONTRACT_ERROR")?;
    if retrieval_version != RETRIEVAL_KERNEL_VERSION {
        return Err(format!(
            "NATIVE_RETRIEVAL_KERNEL_CONTRACT_ERROR: expected retrieval version {RETRIEVAL_KERNEL_VERSION}, found {retrieval_version}"
        ));
    }
    Ok(())
}

fn candidates_from_wire(
    candidates: Vec<RetrievalCandidateWire>,
) -> Result<Vec<RetrievalCandidate>, String> {
    candidates
        .into_iter()
        .map(candidate_from_wire)
        .collect::<Result<Vec<_>, _>>()
}

fn candidate_from_wire(wire: RetrievalCandidateWire) -> Result<RetrievalCandidate, String> {
    RetrievalCandidate::new(
        wire.context_id,
        wire.score,
        wire.fts_score,
        wire.vector_score,
        wire.why_retrieved,
    )
    .map_err(|error| format!("NATIVE_RETRIEVAL_KERNEL_INPUT_ERROR: {error}"))
}

fn encode_response<ResultValue>(
    operation: RetrievalOperationName,
    result: ResultValue,
) -> Result<Vec<u8>, String>
where
    ResultValue: Serialize,
{
    serde_json::to_vec(&RetrievalKernelResponse {
        contract_version: heterarchy_alexandria_core::ComputeContractVersion::CURRENT.value(),
        retrieval_version: RETRIEVAL_KERNEL_VERSION,
        operation,
        result,
    })
    .map_err(|error| format!("NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR: {error}"))
}

#[cfg(test)]
mod tests {
    use serde_json::{Value, json};

    use super::compute_retrieval_kernel_payload;

    #[test]
    fn adapter_runs_one_coarse_best_lane_fusion_request() {
        let payload = br#"{
            "contract_version": 1,
            "retrieval_version": 1,
            "request": {
                "operation": "merge_hybrid",
                "limit": 2,
                "fts_candidates": [
                    {
                        "context_id": "shared",
                        "score": 0.1,
                        "fts_score": 0.1,
                        "vector_score": null,
                        "why_retrieved": "lexical"
                    }
                ],
                "vector_candidates": [
                    {
                        "context_id": "semantic",
                        "score": 0.99,
                        "fts_score": null,
                        "vector_score": 0.99,
                        "why_retrieved": "semantic"
                    },
                    {
                        "context_id": "shared",
                        "score": 0.95,
                        "fts_score": null,
                        "vector_score": 0.95,
                        "why_retrieved": "vector shared"
                    }
                ]
            }
        }"#;
        let encoded = match compute_retrieval_kernel_payload(payload) {
            Ok(value) => value,
            Err(error) => unreachable!("valid retrieval payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("retrieval adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["retrieval_version"], 1);
        assert_eq!(decoded["operation"], "merge_hybrid");
        assert_eq!(decoded["result"][0]["context_id"], "semantic");
        assert_eq!(decoded["result"][1]["representative"]["lane"], "fts");
    }

    #[test]
    fn adapter_runs_candidate_limit_best_match_and_cosine_requests() {
        let limit = request(br#"{"operation":"hybrid_candidate_limit","limit":5}"#);
        assert_eq!(limit["result"], 30);

        let best = request(
            br#"{
                "operation":"rank_best",
                "limit":1,
                "candidates":[
                    {"context_id":"a","score":0.2,"fts_score":0.2,"vector_score":null,"why_retrieved":"low"},
                    {"context_id":"a","score":0.9,"fts_score":0.9,"vector_score":null,"why_retrieved":"high"}
                ]
            }"#,
        );
        assert_eq!(best["result"][0]["candidate_index"], 1);

        let cosine =
            request(br#"{"operation":"cosine_similarity","left":[1.0,0.0],"right":[1.0,0.0]}"#);
        assert_eq!(cosine["result"], json!(1.0));
    }

    #[test]
    fn adapter_rejects_unknown_retrieval_versions_and_fields() {
        let version_payload = br#"{
            "contract_version":1,
            "retrieval_version":2,
            "request":{"operation":"hybrid_candidate_limit","limit":5}
        }"#;
        let Err(version_error) = compute_retrieval_kernel_payload(version_payload) else {
            unreachable!("unknown retrieval version must fail");
        };
        assert!(version_error.contains("expected retrieval version 1, found 2"));

        let unknown_field_payload = br#"{
            "contract_version":1,
            "retrieval_version":1,
            "request":{"operation":"hybrid_candidate_limit","limit":5,"extra":true}
        }"#;
        let Err(field_error) = compute_retrieval_kernel_payload(unknown_field_payload) else {
            unreachable!("unknown request field must fail");
        };
        assert!(field_error.contains("unknown field"));
    }

    fn request(request: &[u8]) -> Value {
        let request_text = match std::str::from_utf8(request) {
            Ok(value) => value,
            Err(error) => unreachable!("test request must be UTF-8: {error}"),
        };
        let payload = format!(
            "{{\"contract_version\":1,\"retrieval_version\":1,\"request\":{request_text}}}"
        );
        let encoded = match compute_retrieval_kernel_payload(payload.as_bytes()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid retrieval request failed: {error}"),
        };
        match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("retrieval response must be JSON: {error}"),
        }
    }
}
