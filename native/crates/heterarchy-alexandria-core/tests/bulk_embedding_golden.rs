//! Live-Python golden parity for bulk embedding preparation and vector validation.

use heterarchy_alexandria_core::bulk_embedding::{
    BulkEmbeddingPolicy, BulkEmbeddingRequest, EmbeddingDocumentInput, EmbeddingInputKind,
    EmbeddingModelContract, InferenceBatchOutput, finalize_embedding_batch,
    prepare_embedding_batch,
};
use heterarchy_alexandria_core::document_analysis::DocumentId;
use serde::Deserialize;
use serde_json::Value;

const GOLDEN_CORPUS: &str = include_str!("../../../corpora/bulk_embedding/v1/cases.json");

#[derive(Debug, Deserialize)]
struct GoldenCorpus {
    schema_version: u16,
    feature: String,
    cases: Vec<GoldenCase>,
}

#[derive(Debug, Deserialize)]
struct GoldenCase {
    case_id: String,
    model: GoldenModel,
    batch_size: usize,
    documents: Vec<GoldenDocument>,
    inference_batches: Option<Vec<GoldenInferenceBatch>>,
    expected_preparation: Value,
    expected_result: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
struct GoldenModel {
    provider: String,
    model: String,
    provider_version: String,
    pooling_mode: String,
    normalize: bool,
    dimensions: usize,
    document_input_format: String,
    input_kind: String,
}

#[derive(Debug, Deserialize)]
struct GoldenDocument {
    item_id: String,
    content: String,
    title: Option<String>,
    heading: Option<String>,
}

#[derive(Debug, Deserialize)]
struct GoldenInferenceBatch {
    batch_index: usize,
    vectors: Vec<Vec<f32>>,
}

#[test]
fn bulk_embedding_matches_the_frozen_python_baseline() {
    let corpus: GoldenCorpus = match serde_json::from_str(GOLDEN_CORPUS) {
        Ok(value) => value,
        Err(error) => unreachable!("bulk embedding corpus must be valid JSON: {error}"),
    };
    assert_eq!(corpus.schema_version, 1);
    assert_eq!(corpus.feature, "bulk_embedding");

    for case in &corpus.cases {
        let request = match request_from_case(case) {
            Ok(value) => value,
            Err(error) => unreachable!("{} request must be valid: {error}", case.case_id),
        };
        let preparation = match prepare_embedding_batch(request) {
            Ok(value) => value,
            Err(error) => unreachable!("{} preparation failed: {error}", case.case_id),
        };
        let actual_preparation = match serde_json::to_value(&preparation) {
            Ok(value) => value,
            Err(error) => unreachable!("{} preparation must serialize: {error}", case.case_id),
        };
        assert_eq!(
            actual_preparation, case.expected_preparation,
            "{} preparation parity",
            case.case_id
        );

        let Some(inference_batches) = &case.inference_batches else {
            assert!(case.expected_result.is_none());
            continue;
        };
        let outputs = inference_batches
            .iter()
            .map(|batch| InferenceBatchOutput::new(batch.batch_index, batch.vectors.clone()))
            .collect();
        let result = match finalize_embedding_batch(preparation, outputs) {
            Ok(value) => value,
            Err(error) => unreachable!("{} finalization failed: {error}", case.case_id),
        };
        let actual_result = match serde_json::to_value(&result) {
            Ok(value) => value,
            Err(error) => unreachable!("{} result must serialize: {error}", case.case_id),
        };
        let Some(expected_result) = &case.expected_result else {
            unreachable!(
                "{} inference case must include expected result",
                case.case_id
            );
        };
        assert_eq!(
            actual_result, *expected_result,
            "{} result parity",
            case.case_id
        );
    }
}

fn request_from_case(case: &GoldenCase) -> Result<BulkEmbeddingRequest, String> {
    let policy = BulkEmbeddingPolicy::new(case.batch_size).map_err(|error| error.to_string())?;
    let documents = case
        .documents
        .iter()
        .map(document_from_golden)
        .collect::<Result<Vec<_>, _>>()?;
    BulkEmbeddingRequest::new(model_from_golden(&case.model)?, policy, documents)
        .map_err(|error| error.to_string())
}

fn model_from_golden(value: &GoldenModel) -> Result<EmbeddingModelContract, String> {
    let input_kind = match value.input_kind.as_str() {
        "plain" => EmbeddingInputKind::Plain,
        "e5_passage" => EmbeddingInputKind::E5Passage,
        other => return Err(format!("unknown embedding input kind: {other}")),
    };
    Ok(EmbeddingModelContract {
        provider: value.provider.clone(),
        model: value.model.clone(),
        provider_version: value.provider_version.clone(),
        pooling_mode: value.pooling_mode.clone(),
        normalize: value.normalize,
        dimensions: value.dimensions,
        document_input_format: value.document_input_format.clone(),
        input_kind,
    })
}

fn document_from_golden(value: &GoldenDocument) -> Result<EmbeddingDocumentInput, String> {
    let item_id = DocumentId::new(value.item_id.clone()).map_err(|error| error.to_string())?;
    EmbeddingDocumentInput::new(
        item_id,
        value.content.clone(),
        value.title.clone(),
        value.heading.clone(),
    )
    .map_err(|error| error.to_string())
}
