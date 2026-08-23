use heterarchy_alexandria_core::reconciliation_candidates::{
    CandidatePolicy, ReconciliationItem, TemporalInterval, discover_candidates,
};
use serde::Deserialize;
use serde_json::Value;

const GOLDEN_CORPUS: &str =
    include_str!("../../../corpora/reconciliation_candidates/v1/cases.json");

#[derive(Debug, Deserialize)]
struct Corpus {
    schema_version: u16,
    candidate_version: u16,
    cases: Vec<Case>,
}

#[derive(Debug, Deserialize)]
struct Case {
    name: String,
    policy: PolicyWire,
    items: Vec<ItemWire>,
    expected: Value,
}

#[derive(Debug, Deserialize)]
struct PolicyWire {
    vector_similarity_threshold: f64,
    graph_similarity_threshold: f64,
    max_block_size: usize,
    max_candidates_per_item: usize,
}

#[derive(Debug, Deserialize)]
struct ItemWire {
    item_id: String,
    content_hash: Option<String>,
    embedding: Option<Vec<f64>>,
    valid_from_micros: Option<i64>,
    valid_to_micros: Option<i64>,
    blocking_keys: Vec<String>,
    graph_neighbors: Vec<String>,
    lineage_ancestors: Vec<String>,
}

#[test]
fn reconciliation_candidates_match_the_frozen_python_baseline() {
    let corpus: Corpus = match serde_json::from_str(GOLDEN_CORPUS) {
        Ok(value) => value,
        Err(error) => unreachable!("golden reconciliation corpus must be valid JSON: {error}"),
    };
    assert_eq!(corpus.schema_version, 1);
    assert_eq!(corpus.candidate_version, 1);
    assert!(!corpus.cases.is_empty());

    for case in corpus.cases {
        let policy = match CandidatePolicy::new(
            case.policy.vector_similarity_threshold,
            case.policy.graph_similarity_threshold,
            case.policy.max_block_size,
            case.policy.max_candidates_per_item,
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("{}: valid policy failed: {error}", case.name),
        };
        let items = case
            .items
            .into_iter()
            .map(|item| item_from_wire(item, &case.name))
            .collect::<Vec<_>>();
        let result = match discover_candidates(&items, policy) {
            Ok(value) => value,
            Err(error) => unreachable!("{}: candidate discovery failed: {error}", case.name),
        };
        let actual = match serde_json::to_value(result) {
            Ok(value) => value,
            Err(error) => unreachable!("{}: result serialization failed: {error}", case.name),
        };
        assert_eq!(actual, case.expected, "{}", case.name);
    }
}

fn item_from_wire(wire: ItemWire, case_name: &str) -> ReconciliationItem {
    let interval = match TemporalInterval::new(wire.valid_from_micros, wire.valid_to_micros) {
        Ok(value) => value,
        Err(error) => unreachable!("{case_name}: valid interval failed: {error}"),
    };
    match ReconciliationItem::new(
        wire.item_id,
        wire.content_hash,
        wire.embedding,
        interval,
        wire.blocking_keys,
        wire.graph_neighbors,
        wire.lineage_ancestors,
    ) {
        Ok(value) => value,
        Err(error) => unreachable!("{case_name}: valid item failed: {error}"),
    }
}
