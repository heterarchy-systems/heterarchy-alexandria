//! Provider-owned `FastEmbed` inference for one initialized multilingual-E5 session.

use std::sync::Mutex;

use fastembed::{
    InitOptionsUserDefined, OwnedFloatTensorInitializer, Pooling, PreparedTextEmbedding,
    QuantizationMode, TextEmbedding, TokenizerFiles,
};
use heterarchy_alexandria_core::bulk_embedding::{
    BulkEmbeddingPreparation, EmbeddingInputKind, InferenceBatchOutput,
};
use heterarchy_alexandria_core::onnx_initializer_projection::{
    InitializerRegistration, project_embedded_float_initializers,
};
use heterarchy_alexandria_model_buffer::ModelBuffer;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

mod embedding_artifact_builder;
pub(crate) use embedding_artifact_builder::{
    MultilingualE5RuntimeBuilder, create_multilingual_e5_runtime_builder,
};

const PROVIDER_NAME: &str = "FASTEMBED_LOCAL";
const MODEL_NAME: &str = "intfloat/multilingual-e5-small";
const DIMENSIONS: usize = 384;
const MAX_LENGTH: usize = 512;
const POOLING_MODE: &str = "mean";
const E5_DOCUMENT_FORMAT_SUFFIX: &str = "+e5-passage-prefix-v1";
const E5_QUERY_PREFIX: &str = "query: ";

pub(crate) const EMBEDDING_RUNTIME_CONTRACT_VERSION: u16 = 4;

/// Provider-owned initialized multilingual-E5 inference session.
#[pyclass(frozen, module = "heterarchy_alexandria_native")]
pub(crate) struct MultilingualE5Session {
    model: Mutex<TextEmbedding>,
}

#[pymethods]
impl MultilingualE5Session {
    /// Embed one query using the exact E5-prefixed input supplied by Python.
    fn embed_query(&self, python: Python<'_>, query_input: String) -> PyResult<Vec<f32>> {
        let model = &self.model;
        python
            .detach(move || {
                let mut model = model.lock().map_err(|_| {
                    "NATIVE_QUERY_EMBEDDING_RUNTIME_ERROR: embedding session lock poisoned"
                        .to_owned()
                })?;
                infer_query_input(&mut model, &query_input)
            })
            .map_err(PyValueError::new_err)
    }

    /// Run one coarse bulk-embedding request against this provider-owned session.
    fn run_bulk_embedding_batch_json<'python>(
        &self,
        python: Python<'python>,
        payload: &[u8],
    ) -> PyResult<Bound<'python, PyBytes>> {
        let owned_payload = payload.to_vec();
        let model = &self.model;
        let encoded = python
            .detach(move || {
                let mut model = model.lock().map_err(|_| {
                    "NATIVE_BULK_EMBEDDING_RUNTIME_ERROR: embedding session lock poisoned"
                        .to_owned()
                })?;
                crate::bulk_embedding_runtime_wire::run_bulk_embedding_payload(
                    &owned_payload,
                    &mut model,
                )
            })
            .map_err(PyValueError::new_err)?;
        Ok(PyBytes::new(python, &encoded))
    }
}

/// Run bounded multilingual-E5 inference for one deterministic preparation plan.
///
/// # Errors
///
/// Returns a sanitized error when the model contract is incompatible or inference fails.
pub(crate) fn infer_prepared_batches(
    preparation: &BulkEmbeddingPreparation,
    model: &mut TextEmbedding,
    batch_size: usize,
) -> Result<Vec<InferenceBatchOutput>, String> {
    validate_model_contract(preparation)?;
    let mut outputs = Vec::with_capacity(preparation.batches.len());
    for batch in &preparation.batches {
        let model_inputs = batch
            .items
            .iter()
            .map(|item| item.model_input.as_str())
            .collect::<Vec<_>>();
        let vectors = model.embed(model_inputs, Some(batch_size)).map_err(|_| {
            format!(
                "NATIVE_BULK_EMBEDDING_INFERENCE_ERROR: FastEmbed failed for batch {}",
                batch.batch_index
            )
        })?;
        outputs.push(InferenceBatchOutput::new(batch.batch_index, vectors));
    }
    Ok(outputs)
}

/// Embed one fully prepared multilingual-E5 query input in its provider-owned session.
///
/// The caller owns query text normalization and must supply the exact `query: `-prefixed
/// model input. Keeping prefix construction at the Python provider boundary preserves the
/// current `str.strip()` semantics until the final authority cutover.
///
/// # Errors
///
/// Returns a sanitized error when the input contract is invalid or inference does not return
/// one 384d vector.
pub(crate) fn infer_query_input(
    model: &mut TextEmbedding,
    query_input: &str,
) -> Result<Vec<f32>, String> {
    validate_query_input(query_input)?;
    let vectors = model
        .embed([query_input], Some(1))
        .map_err(|_| "NATIVE_QUERY_EMBEDDING_INFERENCE_ERROR: FastEmbed query failed".to_owned())?;
    let mut vectors = vectors.into_iter();
    let vector = vectors.next().ok_or_else(|| {
        "NATIVE_QUERY_EMBEDDING_INFERENCE_ERROR: FastEmbed returned no query vector".to_owned()
    })?;
    if vectors.next().is_some() || vector.len() != DIMENSIONS {
        return Err(
            "NATIVE_QUERY_EMBEDDING_INFERENCE_ERROR: FastEmbed returned an unexpected query shape"
                .to_owned(),
        );
    }
    Ok(vector)
}

fn validate_query_input(query_input: &str) -> Result<(), String> {
    if !query_input.starts_with(E5_QUERY_PREFIX) {
        return Err(
            "NATIVE_QUERY_EMBEDDING_CONTRACT_ERROR: multilingual-e5-small query input must start with `query: `"
                .to_owned(),
        );
    }
    Ok(())
}

pub(crate) fn prepare_session(
    onnx: ModelBuffer,
    threads: usize,
) -> Result<PreparedTextEmbedding, String> {
    let projection = project_embedded_float_initializers(onnx.as_ref()).map_err(|error| {
        format!(
            "NATIVE_EMBEDDING_RUNTIME_INPUT_ERROR: invalid ONNX initializer projection: {}",
            error.code()
        )
    })?;
    let options = InitOptionsUserDefined::new()
        .with_max_length(MAX_LENGTH)
        .with_intra_threads(threads);
    let Some(projection) = projection else {
        return TextEmbedding::prepare_from_user_defined_onnx(
            onnx,
            options,
            Some(Pooling::Mean),
            QuantizationMode::None,
            None,
        )
        .map_err(|_| {
            "NATIVE_EMBEDDING_RUNTIME_ERROR: FastEmbed multilingual-e5-small in-memory preparation failed"
                .to_owned()
        });
    };

    let initializers = projection
        .initializers()
        .iter()
        .map(|initializer| {
            OwnedFloatTensorInitializer::from_raw_data(
                initializer.name(),
                initializer.dimensions(),
                initializer.raw_data(),
            )
            .map_err(|_| {
                "NATIVE_EMBEDDING_RUNTIME_INPUT_ERROR: FLOAT initializer construction failed"
                    .to_owned()
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    projection
        .validate_registrations(
            initializers
                .iter()
                .map(|initializer| InitializerRegistration {
                    name: initializer.name(),
                    dimensions: initializer.dimensions(),
                    data_type: initializer.data_type(),
                }),
        )
        .map_err(|error| {
            format!(
                "NATIVE_EMBEDDING_RUNTIME_INPUT_ERROR: initializer registrations are invalid: {}",
                error.code()
            )
        })?;

    let projected_onnx = projection.into_model_bytes();
    drop(onnx);
    TextEmbedding::prepare_from_projected_user_defined_onnx(
        projected_onnx,
        options,
        Some(Pooling::Mean),
        QuantizationMode::None,
        None,
        initializers,
    )
    .map_err(|_| {
        "NATIVE_EMBEDDING_RUNTIME_ERROR: FastEmbed projected multilingual-e5-small preparation failed"
            .to_owned()
    })
}

fn initialize_session(
    prepared: PreparedTextEmbedding,
    tokenizer: Vec<u8>,
    config: Vec<u8>,
    special_tokens_map: Vec<u8>,
    tokenizer_config: Vec<u8>,
) -> Result<MultilingualE5Session, String> {
    let model = prepared
        .finish(TokenizerFiles {
            tokenizer_file: tokenizer,
            config_file: config,
            special_tokens_map_file: special_tokens_map,
            tokenizer_config_file: tokenizer_config,
        })
        .map_err(|_| {
        "NATIVE_EMBEDDING_RUNTIME_ERROR: FastEmbed multilingual-e5-small in-memory initialization failed".to_owned()
    })?;
    Ok(MultilingualE5Session {
        model: Mutex::new(model),
    })
}

fn validate_model_contract(preparation: &BulkEmbeddingPreparation) -> Result<(), String> {
    let model = &preparation.model;
    if model.provider != PROVIDER_NAME {
        return Err(format!(
            "NATIVE_BULK_EMBEDDING_CONTRACT_ERROR: expected provider {PROVIDER_NAME}, found {}",
            model.provider
        ));
    }
    if model.model != MODEL_NAME {
        return Err(format!(
            "NATIVE_BULK_EMBEDDING_CONTRACT_ERROR: expected model {MODEL_NAME}, found {}",
            model.model
        ));
    }
    if model.pooling_mode != POOLING_MODE {
        return Err(format!(
            "NATIVE_BULK_EMBEDDING_CONTRACT_ERROR: expected pooling mode {POOLING_MODE}, found {}",
            model.pooling_mode
        ));
    }
    if !model.normalize {
        return Err(
            "NATIVE_BULK_EMBEDDING_CONTRACT_ERROR: multilingual-e5-small requires normalized vectors"
                .to_owned(),
        );
    }
    if model.dimensions != DIMENSIONS {
        return Err(format!(
            "NATIVE_BULK_EMBEDDING_CONTRACT_ERROR: expected {DIMENSIONS} dimensions, found {}",
            model.dimensions
        ));
    }
    if model.input_kind != EmbeddingInputKind::E5Passage {
        return Err(
            "NATIVE_BULK_EMBEDDING_CONTRACT_ERROR: multilingual-e5-small requires e5_passage input"
                .to_owned(),
        );
    }
    if !model
        .document_input_format
        .ends_with(E5_DOCUMENT_FORMAT_SUFFIX)
    {
        return Err(format!(
            "NATIVE_BULK_EMBEDDING_CONTRACT_ERROR: document input format must end with {E5_DOCUMENT_FORMAT_SUFFIX}"
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use heterarchy_alexandria_core::bulk_embedding::{
        BulkEmbeddingPolicy, BulkEmbeddingRequest, EmbeddingDocumentInput, EmbeddingModelContract,
        prepare_embedding_batch,
    };
    use heterarchy_alexandria_core::document_analysis::DocumentId;

    use super::{
        DIMENSIONS, MODEL_NAME, PROVIDER_NAME, validate_model_contract, validate_query_input,
    };

    #[test]
    fn accepts_the_multilingual_e5_contract_without_initializing_the_model() {
        let preparation = preparation(PROVIDER_NAME, MODEL_NAME, DIMENSIONS, true);
        assert!(validate_model_contract(&preparation).is_ok());
    }

    #[test]
    fn rejects_wrong_dimensions_before_model_initialization() {
        let preparation = preparation(PROVIDER_NAME, MODEL_NAME, DIMENSIONS - 1, true);
        let result = validate_model_contract(&preparation);
        let Err(error) = result else {
            unreachable!("dimension mismatch must fail before runtime initialization");
        };
        assert!(error.contains("expected 384 dimensions"));
    }

    #[test]
    fn rejects_disabled_normalization_before_model_initialization() {
        let preparation = preparation(PROVIDER_NAME, MODEL_NAME, DIMENSIONS, false);
        let result = validate_model_contract(&preparation);
        let Err(error) = result else {
            unreachable!("disabled normalization must fail before runtime initialization");
        };
        assert!(error.contains("requires normalized vectors"));
    }

    #[test]
    fn rejects_query_input_without_e5_prefix_before_model_initialization() {
        let result = validate_query_input("plain query");
        let Err(error) = result else {
            unreachable!("query input without the E5 prefix must fail");
        };
        assert!(error.contains("must start with `query: `"));
    }

    fn preparation(
        provider: &str,
        model: &str,
        dimensions: usize,
        normalize: bool,
    ) -> heterarchy_alexandria_core::bulk_embedding::BulkEmbeddingPreparation {
        let item_id = match DocumentId::new("item-1".to_owned()) {
            Ok(value) => value,
            Err(error) => unreachable!("test item id must be valid: {error}"),
        };
        let document = match EmbeddingDocumentInput::new(
            item_id,
            "body".to_owned(),
            Some("Title".to_owned()),
            None,
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("test document must be valid: {error}"),
        };
        let policy = match BulkEmbeddingPolicy::new(16) {
            Ok(value) => value,
            Err(error) => unreachable!("test policy must be valid: {error}"),
        };
        let request = match BulkEmbeddingRequest::new(
            EmbeddingModelContract {
                provider: provider.to_owned(),
                model: model.to_owned(),
                provider_version: "5.17.4".to_owned(),
                pooling_mode: "mean".to_owned(),
                normalize,
                dimensions,
                document_input_format: "metadata-v1+e5-passage-prefix-v1".to_owned(),
                input_kind:
                    heterarchy_alexandria_core::bulk_embedding::EmbeddingInputKind::E5Passage,
            },
            policy,
            vec![document],
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("test request must be valid: {error}"),
        };
        match prepare_embedding_batch(request) {
            Ok(value) => value,
            Err(error) => unreachable!("test preparation must be valid: {error}"),
        }
    }
}
