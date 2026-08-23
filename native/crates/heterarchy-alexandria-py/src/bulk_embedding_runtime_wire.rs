//! Strict JSON wire for prepare -> `FastEmbed` inference -> finalize in one native call.

use heterarchy_alexandria_core::bulk_embedding::{
    BULK_EMBEDDING_VERSION, BulkEmbeddingPolicy, BulkEmbeddingRequest, EmbeddingDocumentInput,
    EmbeddingInputKind, EmbeddingModelContract, finalize_embedding_batch, prepare_embedding_batch,
};
use heterarchy_alexandria_core::document_analysis::DocumentId;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct BulkEmbeddingRuntimeWire {
    contract_version: u16,
    embedding_version: u16,
    runtime: RuntimeConfigWire,
    request: BulkEmbeddingRequestWire,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeConfigWire {
    cache_directory: Option<String>,
    threads: usize,
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

pub(crate) fn run_bulk_embedding_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: BulkEmbeddingRuntimeWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_INPUT_ERROR: {error}"))?;
    validate_versions(wire.contract_version, wire.embedding_version)?;
    if wire.runtime.threads == 0 {
        return Err(
            "NATIVE_BULK_EMBEDDING_RUNTIME_ERROR: threads must be greater than zero".to_owned(),
        );
    }
    let batch_size = wire.request.batch_size;
    let request = request_from_wire(wire.request)?;
    let preparation = prepare_embedding_batch(request)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_INPUT_ERROR: {error}"))?;
    let inference_batches = crate::fastembed_runtime::infer_prepared_batches(
        &preparation,
        wire.runtime.cache_directory.as_deref(),
        wire.runtime.threads,
        batch_size,
    )?;
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
    use super::run_bulk_embedding_payload;

    #[test]
    fn rejects_zero_runtime_threads_before_model_initialization() {
        let payload = serde_json::json!({
            "contract_version": 1,
            "embedding_version": 1,
            "runtime": {
                "cache_directory": null,
                "threads": 0
            },
            "request": {
                "model": {
                    "provider": "FASTEMBED_LOCAL",
                    "model": "intfloat/multilingual-e5-small",
                    "provider_version": "5.17.4",
                    "pooling_mode": "mean",
                    "normalize": true,
                    "dimensions": 384,
                    "document_input_format": "metadata-v1+e5-passage-prefix-v1",
                    "input_kind": "e5_passage"
                },
                "batch_size": 16,
                "documents": []
            }
        });
        let encoded = match serde_json::to_vec(&payload) {
            Ok(value) => value,
            Err(error) => unreachable!("test payload must serialize: {error}"),
        };
        let result = run_bulk_embedding_payload(&encoded);
        let Err(error) = result else {
            unreachable!("zero runtime threads must fail before initialization");
        };
        assert!(error.contains("threads must be greater than zero"));
    }
}
