//! Live-Python golden parity for canonical hashes and embedding fingerprints.

use heterarchy_alexandria_core::document_analysis::{DocumentId, RelativeVaultPath};
use heterarchy_alexandria_core::hash_fingerprint::{
    CurrentComputeSnapshot, EmbeddingFingerprintInput, HashBatch, HashDocumentInput,
    PreviousComputeSnapshot, compute_hash_batch,
};
use serde::Deserialize;
use serde_json::Value;

const GOLDEN_CORPUS: &str = include_str!("../../../corpora/fingerprint/v1/cases.json");

#[derive(Debug, Deserialize)]
struct GoldenCorpus {
    schema_version: u16,
    feature: String,
    cases: Vec<GoldenCase>,
}

#[derive(Debug, Deserialize)]
struct GoldenCase {
    case_id: String,
    document_id: String,
    relative_path: String,
    text: String,
    embedding_fingerprint: Option<GoldenFingerprint>,
    indexed_at: Option<String>,
    previous: GoldenPrevious,
    current_chunk_identities: Option<Vec<String>>,
    current_edge_identities: Option<Vec<String>>,
    expected: GoldenExpected,
}

#[derive(Debug, Deserialize)]
struct GoldenFingerprint {
    provider: String,
    model: String,
    provider_version: String,
    pooling_mode: String,
    normalize: bool,
    dimensions: i64,
    document_input_format: String,
}

#[derive(Debug, Deserialize)]
struct GoldenPrevious {
    content_hash: Option<String>,
    embedding_fingerprint_key: Option<String>,
    chunk_identities: Option<Vec<String>>,
    edge_identities: Option<Vec<String>>,
}

#[derive(Debug, Deserialize)]
struct GoldenExpected {
    content_hash: String,
    embedding_fingerprint: Option<Value>,
    change_report: Value,
}

#[test]
fn hash_and_fingerprint_results_match_the_frozen_python_baseline() {
    let corpus: GoldenCorpus = match serde_json::from_str(GOLDEN_CORPUS) {
        Ok(value) => value,
        Err(error) => unreachable!("fingerprint corpus must be valid JSON: {error}"),
    };
    assert_eq!(corpus.schema_version, 1);
    assert_eq!(corpus.feature, "fingerprint");

    let documents = corpus
        .cases
        .iter()
        .map(input_from_case)
        .collect::<Result<Vec<_>, _>>();
    let documents = match documents {
        Ok(value) => value,
        Err(error) => unreachable!("golden hash input must be valid: {error}"),
    };
    let batch = match HashBatch::new(documents) {
        Ok(value) => value,
        Err(error) => unreachable!("golden hash batch must be valid: {error}"),
    };
    let result = match compute_hash_batch(batch) {
        Ok(value) => value,
        Err(error) => unreachable!("canonical hash compute failed: {error}"),
    };
    assert_eq!(result.results.len(), corpus.cases.len());

    for (case, actual) in corpus.cases.iter().zip(&result.results) {
        assert_eq!(actual.document_id.as_str(), case.document_id);
        assert_eq!(actual.relative_path.as_str(), case.relative_path);
        assert_eq!(
            actual.content_hash, case.expected.content_hash,
            "{} content digest",
            case.case_id
        );
        assert_eq!(actual.content_hash.len(), 64);
        assert!(
            actual
                .content_hash
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit())
        );
        let actual_fingerprint = match serde_json::to_value(&actual.embedding_fingerprint) {
            Ok(value) => value,
            Err(error) => unreachable!("fingerprint result must serialize: {error}"),
        };
        assert_eq!(
            actual_fingerprint,
            case.expected
                .embedding_fingerprint
                .clone()
                .unwrap_or(Value::Null),
            "{} embedding fingerprint",
            case.case_id
        );
        let actual_change_report = match serde_json::to_value(&actual.change_report) {
            Ok(value) => value,
            Err(error) => unreachable!("change report must serialize: {error}"),
        };
        assert_eq!(
            actual_change_report, case.expected.change_report,
            "{} change report",
            case.case_id
        );
    }
}

fn input_from_case(case: &GoldenCase) -> Result<HashDocumentInput, String> {
    let document_id =
        DocumentId::new(case.document_id.clone()).map_err(|error| error.to_string())?;
    let relative_path =
        RelativeVaultPath::new(case.relative_path.clone()).map_err(|error| error.to_string())?;
    let current = CurrentComputeSnapshot {
        embedding_fingerprint: case
            .embedding_fingerprint
            .as_ref()
            .map(fingerprint_from_golden),
        indexed_at: case.indexed_at.clone(),
        chunk_identities: case.current_chunk_identities.clone(),
        edge_identities: case.current_edge_identities.clone(),
    };
    let previous = PreviousComputeSnapshot {
        content_hash: case.previous.content_hash.clone(),
        embedding_fingerprint_key: case.previous.embedding_fingerprint_key.clone(),
        chunk_identities: case.previous.chunk_identities.clone(),
        edge_identities: case.previous.edge_identities.clone(),
    };
    HashDocumentInput::new(
        document_id,
        relative_path,
        case.text.clone(),
        current,
        previous,
    )
    .map_err(|error| error.to_string())
}

fn fingerprint_from_golden(value: &GoldenFingerprint) -> EmbeddingFingerprintInput {
    EmbeddingFingerprintInput::new(
        value.provider.clone(),
        value.model.clone(),
        value.provider_version.clone(),
        value.pooling_mode.clone(),
        value.normalize,
        value.dimensions,
        value.document_input_format.clone(),
    )
}
