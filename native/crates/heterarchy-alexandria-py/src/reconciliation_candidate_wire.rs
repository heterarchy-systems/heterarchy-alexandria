//! Strict JSON wire conversion for bounded reconciliation candidate discovery.

use heterarchy_alexandria_core::reconciliation_candidates::{
    CandidatePolicy, RECONCILIATION_CANDIDATE_VERSION, ReconciliationItem, TemporalInterval,
    discover_candidates,
};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CandidateEnvelopeWire {
    contract_version: u16,
    candidate_version: u16,
    policy: CandidatePolicyWire,
    items: Vec<ReconciliationItemWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CandidatePolicyWire {
    vector_similarity_threshold: f64,
    graph_similarity_threshold: f64,
    max_block_size: usize,
    max_candidates_per_item: usize,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ReconciliationItemWire {
    item_id: String,
    content_hash: Option<String>,
    embedding: Option<Vec<f64>>,
    valid_from_micros: Option<i64>,
    valid_to_micros: Option<i64>,
    blocking_keys: Vec<String>,
    graph_neighbors: Vec<String>,
    lineage_ancestors: Vec<String>,
}

pub(crate) fn compute_reconciliation_candidates_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: CandidateEnvelopeWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_RECONCILIATION_CANDIDATE_INPUT_ERROR: {error}"))?;
    crate::validate_contract_version(
        wire.contract_version,
        "NATIVE_RECONCILIATION_CANDIDATE_CONTRACT_ERROR",
    )?;
    if wire.candidate_version != RECONCILIATION_CANDIDATE_VERSION {
        return Err(format!(
            "NATIVE_RECONCILIATION_CANDIDATE_CONTRACT_ERROR: expected candidate version {RECONCILIATION_CANDIDATE_VERSION}, found {}",
            wire.candidate_version
        ));
    }
    let policy = CandidatePolicy::new(
        wire.policy.vector_similarity_threshold,
        wire.policy.graph_similarity_threshold,
        wire.policy.max_block_size,
        wire.policy.max_candidates_per_item,
    )
    .map_err(|error| format!("NATIVE_RECONCILIATION_CANDIDATE_INPUT_ERROR: {error}"))?;
    let items = wire
        .items
        .into_iter()
        .map(item_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let result = discover_candidates(&items, policy)
        .map_err(|error| format!("NATIVE_RECONCILIATION_CANDIDATE_RESULT_ERROR: {error}"))?;
    serde_json::to_vec(&result)
        .map_err(|error| format!("NATIVE_RECONCILIATION_CANDIDATE_OUTPUT_ERROR: {error}"))
}

fn item_from_wire(wire: ReconciliationItemWire) -> Result<ReconciliationItem, String> {
    let interval = TemporalInterval::new(wire.valid_from_micros, wire.valid_to_micros)
        .map_err(|error| format!("NATIVE_RECONCILIATION_CANDIDATE_INPUT_ERROR: {error}"))?;
    ReconciliationItem::new(
        wire.item_id,
        wire.content_hash,
        wire.embedding,
        interval,
        wire.blocking_keys,
        wire.graph_neighbors,
        wire.lineage_ancestors,
    )
    .map_err(|error| format!("NATIVE_RECONCILIATION_CANDIDATE_INPUT_ERROR: {error}"))
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::compute_reconciliation_candidates_payload;

    #[test]
    fn adapter_runs_one_coarse_candidate_discovery_request() {
        let payload = br#"{
            "contract_version":1,
            "candidate_version":1,
            "policy":{
                "vector_similarity_threshold":0.8,
                "graph_similarity_threshold":0.5,
                "max_block_size":16,
                "max_candidates_per_item":8
            },
            "items":[
                {
                    "item_id":"old",
                    "content_hash":null,
                    "embedding":[1.0,0.0],
                    "valid_from_micros":10,
                    "valid_to_micros":20,
                    "blocking_keys":["topic"],
                    "graph_neighbors":["shared"],
                    "lineage_ancestors":[]
                },
                {
                    "item_id":"new",
                    "content_hash":null,
                    "embedding":[0.99,0.01],
                    "valid_from_micros":15,
                    "valid_to_micros":30,
                    "blocking_keys":["topic"],
                    "graph_neighbors":["shared"],
                    "lineage_ancestors":["old"]
                }
            ]
        }"#;
        let encoded = match compute_reconciliation_candidates_payload(payload) {
            Ok(value) => value,
            Err(error) => unreachable!("valid reconciliation payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("candidate adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["candidate_version"], 1);
        assert_eq!(decoded["candidate_pairs"].as_array().map(Vec::len), Some(1));
        assert_eq!(
            decoded["candidate_pairs"][0]["lineage"],
            "left_descends_from_right"
        );
    }

    #[test]
    fn adapter_rejects_unknown_candidate_versions_and_fields() {
        let version_payload = br#"{
            "contract_version":1,
            "candidate_version":2,
            "policy":{
                "vector_similarity_threshold":0.8,
                "graph_similarity_threshold":0.5,
                "max_block_size":16,
                "max_candidates_per_item":8
            },
            "items":[]
        }"#;
        let Err(version_error) = compute_reconciliation_candidates_payload(version_payload) else {
            unreachable!("unknown candidate version must fail");
        };
        assert!(version_error.contains("expected candidate version 1, found 2"));

        let field_payload = br#"{
            "contract_version":1,
            "candidate_version":1,
            "policy":{
                "vector_similarity_threshold":0.8,
                "graph_similarity_threshold":0.5,
                "max_block_size":16,
                "max_candidates_per_item":8,
                "extra":true
            },
            "items":[]
        }"#;
        let Err(field_error) = compute_reconciliation_candidates_payload(field_payload) else {
            unreachable!("unknown candidate field must fail");
        };
        assert!(field_error.contains("unknown field"));
    }
}
