//! Process-scoped `FastEmbed` inference for the Rust-owned bulk embedding candidate.

use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};

use fastembed::{EmbeddingModel, TextEmbedding, TextInitOptions};
use heterarchy_alexandria_core::bulk_embedding::{
    BulkEmbeddingPreparation, EmbeddingInputKind, InferenceBatchOutput,
};

use crate::embedding_runtime_registry::{
    EmbeddingRuntimeError, EmbeddingRuntimeIdentity, EmbeddingRuntimeRegistry,
};

const RUNTIME_NAME: &str = "fastembed-rs";
const PROVIDER_NAME: &str = "FASTEMBED_LOCAL";
const MODEL_NAME: &str = "intfloat/multilingual-e5-small";
const DIMENSIONS: usize = 384;
const POOLING_MODE: &str = "mean";
const E5_DOCUMENT_FORMAT_SUFFIX: &str = "+e5-passage-prefix-v1";
const E5_QUERY_PREFIX: &str = "query: ";

struct FastEmbedSession {
    model: Mutex<TextEmbedding>,
}

static RUNTIME_REGISTRY: OnceLock<EmbeddingRuntimeRegistry<FastEmbedSession>> = OnceLock::new();

/// Run bounded multilingual-E5 inference for one deterministic preparation plan.
///
/// # Errors
///
/// Returns a sanitized error when the model contract is incompatible, the process-scoped
/// `FastEmbed` runtime cannot initialize, its mutex is poisoned, or inference fails.
pub(crate) fn infer_prepared_batches(
    preparation: &BulkEmbeddingPreparation,
    cache_directory: Option<&str>,
    threads: usize,
    batch_size: usize,
) -> Result<Vec<InferenceBatchOutput>, String> {
    validate_model_contract(preparation)?;
    let identity = EmbeddingRuntimeIdentity::new(
        RUNTIME_NAME.to_owned(),
        MODEL_NAME.to_owned(),
        DIMENSIONS,
        cache_directory.map(str::to_owned),
        threads,
    )
    .map_err(|error| format!("NATIVE_BULK_EMBEDDING_RUNTIME_ERROR: {error}"))?;
    let session = runtime_registry()
        .session_or_initialize(&identity, initialize_session)
        .map_err(|error| format!("NATIVE_BULK_EMBEDDING_RUNTIME_ERROR: {error}"))?;
    let mut model = session.model.lock().map_err(|_| {
        "NATIVE_BULK_EMBEDDING_RUNTIME_ERROR: embedding runtime lock poisoned".to_owned()
    })?;
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

/// Embed one fully prepared multilingual-E5 query input using the shared process session.
///
/// The caller owns query text normalization and must supply the exact `query: `-prefixed
/// model input. Keeping prefix construction at the Python provider boundary preserves the
/// current `str.strip()` semantics until the final authority cutover.
///
/// # Errors
///
/// Returns a sanitized error when the input contract is invalid, the shared runtime cannot
/// initialize, its mutex is poisoned, or inference does not return exactly one 384d vector.
pub(crate) fn infer_query_input(
    query_input: &str,
    cache_directory: Option<&str>,
    threads: usize,
) -> Result<Vec<f32>, String> {
    if !query_input.starts_with(E5_QUERY_PREFIX) {
        return Err(
            "NATIVE_QUERY_EMBEDDING_CONTRACT_ERROR: multilingual-e5-small query input must start with `query: `"
                .to_owned(),
        );
    }
    let identity = EmbeddingRuntimeIdentity::new(
        RUNTIME_NAME.to_owned(),
        MODEL_NAME.to_owned(),
        DIMENSIONS,
        cache_directory.map(str::to_owned),
        threads,
    )
    .map_err(|error| format!("NATIVE_QUERY_EMBEDDING_RUNTIME_ERROR: {error}"))?;
    let session = runtime_registry()
        .session_or_initialize(&identity, initialize_session)
        .map_err(|error| format!("NATIVE_QUERY_EMBEDDING_RUNTIME_ERROR: {error}"))?;
    let mut model = session.model.lock().map_err(|_| {
        "NATIVE_QUERY_EMBEDDING_RUNTIME_ERROR: embedding runtime lock poisoned".to_owned()
    })?;
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

fn runtime_registry() -> &'static EmbeddingRuntimeRegistry<FastEmbedSession> {
    RUNTIME_REGISTRY.get_or_init(EmbeddingRuntimeRegistry::new)
}

fn initialize_session(
    identity: &EmbeddingRuntimeIdentity,
) -> Result<FastEmbedSession, EmbeddingRuntimeError> {
    let mut options = TextInitOptions::new(EmbeddingModel::MultilingualE5Small)
        .with_show_download_progress(false)
        .with_intra_threads(identity.threads());
    if let Some(cache_directory) = identity.cache_directory() {
        options = options.with_cache_dir(PathBuf::from(cache_directory));
    }
    let model = TextEmbedding::try_new(options).map_err(|_| {
        EmbeddingRuntimeError::backend_initialization(
            "FastEmbed multilingual-e5-small initialization failed",
        )
    })?;
    Ok(FastEmbedSession {
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
        DIMENSIONS, MODEL_NAME, PROVIDER_NAME, infer_query_input, validate_model_contract,
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
        let result = infer_query_input("plain query", None, 4);
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
