//! Strict JSON wire conversion for deterministic bulk embedding preparation and validation.

use heterarchy_alexandria_core::bulk_embedding::{
    BULK_EMBEDDING_VERSION, BulkEmbeddingPolicy, BulkEmbeddingRequest, EmbeddingDocumentInput,
    EmbeddingInputKind, EmbeddingModelContract, InferenceBatchOutput, finalize_embedding_batch,
    prepare_embedding_batch,
};
use heterarchy_alexandria_core::document_analysis::DocumentId;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct BulkEmbeddingPreparationWire {
    contract_version: u16,
    embedding_version: u16,
    request: BulkEmbeddingRequestWire,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct BulkEmbeddingFinalizationWire {
    contract_version: u16,
    embedding_version: u16,
    request: BulkEmbeddingRequestWire,
    inference_batches: Vec<InferenceBatchWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct BulkEmbeddingRequestWire {
    model: EmbeddingModelWire,
    batch_size: usize,
    documents: Vec<EmbeddingDocumentWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct EmbeddingModelWire {
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
#[serde(deny_unknown_fields)]
struct EmbeddingDocumentWire {
    item_id: String,
    content: String,
    title: Option<String>,
    heading: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct InferenceBatchWire {
    batch_index: usize,
    vectors: Vec<Vec<f32>>,
}

pub(crate) fn prepare_bulk_embedding_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: BulkEmbeddingPreparationWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_INPUT_ERROR: {error}"))?;
    validate_versions(wire.contract_version, wire.embedding_version)?;
    let request = request_from_wire(wire.request)?;
    let preparation = prepare_embedding_batch(request)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_INPUT_ERROR: {error}"))?;
    serde_json::to_vec(&preparation)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_OUTPUT_ERROR: {error}"))
}

pub(crate) fn finalize_bulk_embedding_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: BulkEmbeddingFinalizationWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_INPUT_ERROR: {error}"))?;
    validate_versions(wire.contract_version, wire.embedding_version)?;
    let request = request_from_wire(wire.request)?;
    let preparation = prepare_embedding_batch(request)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_INPUT_ERROR: {error}"))?;
    let inference_batches = wire
        .inference_batches
        .into_iter()
        .map(|batch| InferenceBatchOutput::new(batch.batch_index, batch.vectors))
        .collect();
    let result = finalize_embedding_batch(preparation, inference_batches)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_RESULT_ERROR: {error}"))?;
    serde_json::to_vec(&result)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_OUTPUT_ERROR: {error}"))
}

fn validate_versions(contract_version: u16, embedding_version: u16) -> Result<(), String> {
    crate::validate_contract_version(contract_version, "NATIVE_BULK_EMBEDDING_CONTRACT_ERROR")?;
    if embedding_version != BULK_EMBEDDING_VERSION {
        return Err(format!(
            "NATIVE_BULK_EMBEDDING_CONTRACT_ERROR: expected embedding version {BULK_EMBEDDING_VERSION}, found {embedding_version}"
        ));
    }
    Ok(())
}

fn request_from_wire(wire: BulkEmbeddingRequestWire) -> Result<BulkEmbeddingRequest, String> {
    let policy = BulkEmbeddingPolicy::new(wire.batch_size)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_INPUT_ERROR: {error}"))?;
    let model = model_from_wire(wire.model)?;
    let documents = wire
        .documents
        .into_iter()
        .map(document_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    BulkEmbeddingRequest::new(model, policy, documents)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_INPUT_ERROR: {error}"))
}

fn model_from_wire(wire: EmbeddingModelWire) -> Result<EmbeddingModelContract, String> {
    let input_kind = match wire.input_kind.as_str() {
        "plain" => EmbeddingInputKind::Plain,
        "e5_passage" => EmbeddingInputKind::E5Passage,
        other => {
            return Err(format!(
                "NATIVE_BULK_EMBEDDING_INPUT_ERROR: unknown embedding input kind {other}"
            ));
        }
    };
    Ok(EmbeddingModelContract {
        provider: wire.provider,
        model: wire.model,
        provider_version: wire.provider_version,
        pooling_mode: wire.pooling_mode,
        normalize: wire.normalize,
        dimensions: wire.dimensions,
        document_input_format: wire.document_input_format,
        input_kind,
    })
}

fn document_from_wire(wire: EmbeddingDocumentWire) -> Result<EmbeddingDocumentInput, String> {
    let item_id = DocumentId::new(wire.item_id)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_INPUT_ERROR: {error}"))?;
    EmbeddingDocumentInput::new(item_id, wire.content, wire.title, wire.heading)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_INPUT_ERROR: {error}"))
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::{finalize_bulk_embedding_payload, prepare_bulk_embedding_payload};

    const REQUEST: &str = r#"
        "request": {
            "model": {
                "provider": "GOLDEN_SYNTHETIC",
                "model": "synthetic-3d",
                "provider_version": "1",
                "pooling_mode": "none",
                "normalize": false,
                "dimensions": 3,
                "document_input_format": "metadata-v1",
                "input_kind": "plain"
            },
            "batch_size": 2,
            "documents": [
                {"item_id":"a","content":" body ","title":"Title","heading":null},
                {"item_id":"b","content":"second","title":null,"heading":null}
            ]
        }
    "#;

    #[test]
    fn adapter_prepares_one_coarse_bulk_embedding_request() {
        let payload = format!("{{\"contract_version\":1,\"embedding_version\":1,{REQUEST}}}");
        let encoded = match prepare_bulk_embedding_payload(payload.as_bytes()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid preparation payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("preparation adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["embedding_version"], 1);
        assert_eq!(decoded["batches"][0]["items"][0]["item_id"], "a");
        assert_eq!(
            decoded["batches"][0]["items"][0]["document_text"],
            "Title: Title\n\nbody"
        );
    }

    #[test]
    fn adapter_finalizes_one_coarse_bulk_embedding_request() {
        let payload = format!(
            "{{\"contract_version\":1,\"embedding_version\":1,{REQUEST},\"inference_batches\":[{{\"batch_index\":0,\"vectors\":[[3.0,4.0,0.0],[0.25,-0.5,1.0]]}}]}}"
        );
        let encoded = match finalize_bulk_embedding_payload(payload.as_bytes()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid finalization payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("finalization adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(
            decoded["records"][0]["vector"],
            serde_json::json!([3.0, 4.0, 0.0])
        );
        assert_eq!(decoded["metrics"]["vector_value_count"], 6);
    }

    #[test]
    fn adapter_rejects_unknown_bulk_embedding_versions() {
        let payload = format!("{{\"contract_version\":1,\"embedding_version\":2,{REQUEST}}}");
        let result = prepare_bulk_embedding_payload(payload.as_bytes());
        let Err(error) = result else {
            unreachable!("unsupported embedding version must fail");
        };
        assert!(error.contains("expected embedding version 1, found 2"));
    }
}
