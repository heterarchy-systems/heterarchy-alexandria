//! Typed deterministic preparation and validation for bulk embedding inference.

mod finalization;
mod preparation;

use std::error::Error;
use std::fmt::{Display, Formatter};

use serde::Serialize;

use crate::ComputeContractVersion;
use crate::document_analysis::DocumentId;
use crate::text_compat::trim_python_whitespace;

pub use finalization::finalize_embedding_batch;
pub use preparation::prepare_embedding_batch;

/// Version of the bulk-embedding preparation and result schema.
pub const BULK_EMBEDDING_VERSION: u16 = 1;

const MAX_ITEMS_PER_REQUEST: usize = 100_000;
const MAX_ITEM_BYTES: usize = 16 * 1024 * 1024;
const MAX_REQUEST_BYTES: usize = 256 * 1024 * 1024;
const MAX_INFERENCE_BATCH_SIZE: usize = 4_096;
const MAX_VECTOR_DIMENSIONS: usize = 65_536;

/// Model-input transformation selected by Python configuration authority.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EmbeddingInputKind {
    /// Submit the deterministic document text unchanged.
    Plain,
    /// Prefix stripped document text with the multilingual-E5 passage marker.
    E5Passage,
}

/// Exact provider/model identity supplied by the Python effect boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct EmbeddingModelContract {
    /// Stable provider identity.
    pub provider: String,
    /// Stable model identity.
    pub model: String,
    /// Installed provider/runtime version.
    pub provider_version: String,
    /// Pooling mode used by inference.
    pub pooling_mode: String,
    /// Whether the provider emits normalized vectors.
    pub normalize: bool,
    /// Required output dimensions.
    pub dimensions: usize,
    /// Versioned document composition identifier.
    pub document_input_format: String,
    /// Model-specific input transformation.
    pub input_kind: EmbeddingInputKind,
}

impl EmbeddingModelContract {
    fn validate(&self) -> Result<(), BulkEmbeddingError> {
        for (field_name, value) in [
            ("provider", self.provider.as_str()),
            ("model", self.model.as_str()),
            ("provider_version", self.provider_version.as_str()),
            ("pooling_mode", self.pooling_mode.as_str()),
            ("document_input_format", self.document_input_format.as_str()),
        ] {
            if trim_python_whitespace(value).is_empty() {
                return Err(BulkEmbeddingError::invalid_input(format!(
                    "{field_name} must not be blank"
                )));
            }
            if value.contains('\0') {
                return Err(BulkEmbeddingError::invalid_input(format!(
                    "{field_name} must not contain a null byte"
                )));
            }
        }
        if self.dimensions == 0 || self.dimensions > MAX_VECTOR_DIMENSIONS {
            return Err(BulkEmbeddingError::invalid_input(format!(
                "dimensions must be between 1 and {MAX_VECTOR_DIMENSIONS}"
            )));
        }
        Ok(())
    }
}

/// Caller-selected bounded inference batch policy.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct BulkEmbeddingPolicy {
    /// Maximum prepared items in one inference call.
    pub batch_size: usize,
}

impl BulkEmbeddingPolicy {
    /// Create a bounded inference policy.
    ///
    /// # Errors
    ///
    /// Returns an error when the batch size is zero or exceeds the safety bound.
    pub fn new(batch_size: usize) -> Result<Self, BulkEmbeddingError> {
        if batch_size == 0 || batch_size > MAX_INFERENCE_BATCH_SIZE {
            return Err(BulkEmbeddingError::invalid_input(format!(
                "batch_size must be between 1 and {MAX_INFERENCE_BATCH_SIZE}"
            )));
        }
        Ok(Self { batch_size })
    }
}

/// One caller-owned chunk submitted for deterministic embedding preparation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmbeddingDocumentInput {
    pub(super) item_id: DocumentId,
    pub(super) content: String,
    pub(super) title: Option<String>,
    pub(super) heading: Option<String>,
}

impl EmbeddingDocumentInput {
    /// Create one bounded document input.
    ///
    /// # Errors
    ///
    /// Returns an error when combined content and metadata exceed the per-item limit.
    pub fn new(
        item_id: DocumentId,
        content: String,
        title: Option<String>,
        heading: Option<String>,
    ) -> Result<Self, BulkEmbeddingError> {
        let byte_count = [
            content.len(),
            title.as_ref().map_or(0, String::len),
            heading.as_ref().map_or(0, String::len),
        ]
        .into_iter()
        .try_fold(0_usize, usize::checked_add)
        .ok_or_else(|| BulkEmbeddingError::invalid_input("embedding item byte count overflow"))?;
        if byte_count > MAX_ITEM_BYTES {
            return Err(BulkEmbeddingError::invalid_input(format!(
                "embedding item {} exceeds the {MAX_ITEM_BYTES} byte limit",
                item_id.as_str()
            )));
        }
        Ok(Self {
            item_id,
            content,
            title,
            heading,
        })
    }

    fn byte_count(&self) -> usize {
        self.content.len()
            + self.title.as_ref().map_or(0, String::len)
            + self.heading.as_ref().map_or(0, String::len)
    }
}

/// Validated coarse-grained request for deterministic preparation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BulkEmbeddingRequest {
    pub(super) model: EmbeddingModelContract,
    pub(super) policy: BulkEmbeddingPolicy,
    pub(super) documents: Vec<EmbeddingDocumentInput>,
}

impl BulkEmbeddingRequest {
    /// Validate the model contract, cardinality, and total input bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the request violates a deterministic safety bound.
    pub fn new(
        model: EmbeddingModelContract,
        policy: BulkEmbeddingPolicy,
        documents: Vec<EmbeddingDocumentInput>,
    ) -> Result<Self, BulkEmbeddingError> {
        model.validate()?;
        if documents.len() > MAX_ITEMS_PER_REQUEST {
            return Err(BulkEmbeddingError::invalid_input(format!(
                "embedding request exceeds the {MAX_ITEMS_PER_REQUEST} item limit"
            )));
        }
        let total_bytes = documents.iter().try_fold(0_usize, |total, document| {
            total.checked_add(document.byte_count()).ok_or_else(|| {
                BulkEmbeddingError::invalid_input("embedding request byte count overflow")
            })
        })?;
        if total_bytes > MAX_REQUEST_BYTES {
            return Err(BulkEmbeddingError::invalid_input(format!(
                "embedding request exceeds the {MAX_REQUEST_BYTES} byte limit"
            )));
        }
        Ok(Self {
            model,
            policy,
            documents,
        })
    }
}

/// One prepared item retaining exact caller order and identity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PreparedEmbeddingItem {
    /// Original zero-based request position.
    pub input_index: usize,
    /// Stable caller-owned item identity.
    pub item_id: String,
    /// Metadata-aware document text before model-specific transformation.
    pub document_text: String,
    /// Exact text submitted to the inference runtime.
    pub model_input: String,
}

/// One bounded inference batch.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PreparedEmbeddingBatch {
    /// Stable zero-based inference sequence.
    pub batch_index: usize,
    /// Ordered prepared items.
    pub items: Vec<PreparedEmbeddingItem>,
}

/// Deterministic preparation metrics excluding runtime inference work.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct BulkEmbeddingPreparationMetrics {
    /// Input item count.
    pub item_count: usize,
    /// Planned inference call count.
    pub batch_count: usize,
    /// Raw content and metadata bytes accepted.
    pub source_bytes: usize,
    /// Metadata-aware document text bytes.
    pub document_text_bytes: usize,
    /// Exact model input bytes.
    pub model_input_bytes: usize,
}

/// Fully prepared inference plan with no model or persistence effects.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BulkEmbeddingPreparation {
    /// Coarse native contract version.
    pub contract_version: u16,
    /// Bulk embedding schema version.
    pub embedding_version: u16,
    /// Exact caller-selected model contract.
    pub model: EmbeddingModelContract,
    /// Deterministic bounded inference batches.
    pub batches: Vec<PreparedEmbeddingBatch>,
    /// Preparation metrics.
    pub metrics: BulkEmbeddingPreparationMetrics,
}

/// One runtime-owned inference response for an exact prepared batch.
#[derive(Debug, Clone, PartialEq)]
pub struct InferenceBatchOutput {
    /// Batch index copied from the preparation plan.
    pub batch_index: usize,
    /// Ordered vectors corresponding one-to-one with prepared items.
    pub vectors: Vec<Vec<f32>>,
}

impl InferenceBatchOutput {
    /// Construct one raw inference batch result.
    #[must_use]
    pub const fn new(batch_index: usize, vectors: Vec<Vec<f32>>) -> Self {
        Self {
            batch_index,
            vectors,
        }
    }
}

/// One validated vector ready for Python-owned persistence.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct EmbeddingRecord {
    /// Original zero-based request position.
    pub input_index: usize,
    /// Stable caller-owned item identity.
    pub item_id: String,
    /// Finite vector values in provider output order.
    pub vector: Vec<f32>,
    /// Exact vector dimensions.
    pub dimensions: usize,
}

/// Validated inference result metrics.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct BulkEmbeddingResultMetrics {
    /// Validated output vector count.
    pub item_count: usize,
    /// Validated inference batch count.
    pub batch_count: usize,
    /// Exact dimensions per vector.
    pub dimensions: usize,
    /// Total scalar values returned.
    pub vector_value_count: usize,
}

/// Ordered validated vectors with model identity and no persistence effects.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct BulkEmbeddingResult {
    /// Coarse native contract version.
    pub contract_version: u16,
    /// Bulk embedding schema version.
    pub embedding_version: u16,
    /// Exact caller-selected model contract.
    pub model: EmbeddingModelContract,
    /// Ordered validated vectors.
    pub records: Vec<EmbeddingRecord>,
    /// Result metrics.
    pub metrics: BulkEmbeddingResultMetrics,
}

/// Stable typed failure category for preparation or inference validation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BulkEmbeddingErrorCode {
    /// Invalid caller input or safety-bound violation.
    InvalidInput,
    /// Runtime output did not preserve required cardinality/order.
    CardinalityMismatch,
    /// Runtime vector dimensions differ from the model contract.
    DimensionMismatch,
    /// Runtime emitted NaN or infinity.
    NonFiniteVector,
    /// A metrics calculation overflowed.
    NumericOverflow,
}

/// Structured fail-fast error matching the current Python batch policy.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BulkEmbeddingError {
    /// Stable failure category.
    pub code: BulkEmbeddingErrorCode,
    /// Non-secret diagnostic message.
    pub message: String,
    /// Optional inference batch index.
    pub batch_index: Option<usize>,
    /// Optional original input index.
    pub input_index: Option<usize>,
    /// Optional caller-owned item identity.
    pub item_id: Option<String>,
}

impl BulkEmbeddingError {
    fn invalid_input(message: impl Into<String>) -> Self {
        Self {
            code: BulkEmbeddingErrorCode::InvalidInput,
            message: message.into(),
            batch_index: None,
            input_index: None,
            item_id: None,
        }
    }

    fn batch(code: BulkEmbeddingErrorCode, message: impl Into<String>, batch_index: usize) -> Self {
        Self {
            code,
            message: message.into(),
            batch_index: Some(batch_index),
            input_index: None,
            item_id: None,
        }
    }

    fn item(
        code: BulkEmbeddingErrorCode,
        message: impl Into<String>,
        batch_index: usize,
        item: &PreparedEmbeddingItem,
    ) -> Self {
        Self {
            code,
            message: message.into(),
            batch_index: Some(batch_index),
            input_index: Some(item.input_index),
            item_id: Some(item.item_id.clone()),
        }
    }
}

impl Display for BulkEmbeddingError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for BulkEmbeddingError {}

fn current_contract_version() -> u16 {
    ComputeContractVersion::CURRENT.value()
}

#[cfg(test)]
mod tests {
    use super::{
        BulkEmbeddingErrorCode, BulkEmbeddingPolicy, BulkEmbeddingRequest, EmbeddingDocumentInput,
        EmbeddingInputKind, EmbeddingModelContract, InferenceBatchOutput, finalize_embedding_batch,
        prepare_embedding_batch,
    };
    use crate::document_analysis::DocumentId;

    fn model(input_kind: EmbeddingInputKind) -> EmbeddingModelContract {
        EmbeddingModelContract {
            provider: "FASTEMBED_LOCAL".to_owned(),
            model: "intfloat/multilingual-e5-small".to_owned(),
            provider_version: "0.8.0".to_owned(),
            pooling_mode: "mean".to_owned(),
            normalize: true,
            dimensions: 3,
            document_input_format: "metadata-v1+e5-passage-prefix-v1".to_owned(),
            input_kind,
        }
    }

    fn document(
        item_id: &str,
        content: &str,
        title: Option<&str>,
        heading: Option<&str>,
    ) -> EmbeddingDocumentInput {
        let document_id = match DocumentId::new(item_id.to_owned()) {
            Ok(value) => value,
            Err(error) => unreachable!("test item id must be valid: {error}"),
        };
        match EmbeddingDocumentInput::new(
            document_id,
            content.to_owned(),
            title.map(str::to_owned),
            heading.map(str::to_owned),
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("test document must be valid: {error}"),
        }
    }

    fn policy(batch_size: usize) -> BulkEmbeddingPolicy {
        match BulkEmbeddingPolicy::new(batch_size) {
            Ok(value) => value,
            Err(error) => unreachable!("test policy must be valid: {error}"),
        }
    }

    #[test]
    fn prepares_python_compatible_metadata_text_and_e5_input() {
        let request = match BulkEmbeddingRequest::new(
            model(EmbeddingInputKind::E5Passage),
            policy(2),
            vec![
                document(
                    "chunk-1",
                    "  검색 품질은 rank fusion으로 평가한다.  ",
                    Some(" Alexandria\n 검색 "),
                    Some(" Hybrid\t ranking "),
                ),
                document(
                    "chunk-2",
                    " body ",
                    Some("Same\u{3000}Heading"),
                    Some("Same Heading"),
                ),
            ],
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid preparation request failed: {error}"),
        };
        let prepared = match prepare_embedding_batch(request) {
            Ok(value) => value,
            Err(error) => unreachable!("valid preparation failed: {error}"),
        };

        assert_eq!(prepared.batches.len(), 1);
        assert_eq!(
            prepared.batches[0].items[0].document_text,
            "Title: Alexandria 검색\nHeading: Hybrid ranking\n\n검색 품질은 rank fusion으로 평가한다."
        );
        assert_eq!(
            prepared.batches[0].items[0].model_input,
            "passage: Title: Alexandria 검색\nHeading: Hybrid ranking\n\n검색 품질은 rank fusion으로 평가한다."
        );
        assert_eq!(
            prepared.batches[0].items[1].document_text,
            "Title: Same Heading\n\nbody"
        );
    }

    #[test]
    fn preserves_input_order_and_deterministic_batch_boundaries() {
        let request = match BulkEmbeddingRequest::new(
            model(EmbeddingInputKind::Plain),
            policy(2),
            vec![
                document("chunk-b", "b", None, None),
                document("chunk-a", "a", None, None),
                document("chunk-c", "c", None, None),
            ],
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid preparation request failed: {error}"),
        };
        let prepared = match prepare_embedding_batch(request) {
            Ok(value) => value,
            Err(error) => unreachable!("valid preparation failed: {error}"),
        };

        assert_eq!(prepared.batches.len(), 2);
        assert_eq!(prepared.batches[0].batch_index, 0);
        assert_eq!(prepared.batches[1].batch_index, 1);
        assert_eq!(prepared.batches[0].items[0].item_id, "chunk-b");
        assert_eq!(prepared.batches[0].items[1].item_id, "chunk-a");
        assert_eq!(prepared.batches[1].items[0].input_index, 2);
    }

    #[test]
    fn validates_runtime_vectors_without_mathematical_renormalization() {
        let request = match BulkEmbeddingRequest::new(
            model(EmbeddingInputKind::Plain),
            policy(2),
            vec![
                document("chunk-1", "one", None, None),
                document("chunk-2", "two", None, None),
            ],
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid preparation request failed: {error}"),
        };
        let prepared = match prepare_embedding_batch(request) {
            Ok(value) => value,
            Err(error) => unreachable!("valid preparation failed: {error}"),
        };
        let result = match finalize_embedding_batch(
            prepared,
            vec![InferenceBatchOutput::new(
                0,
                vec![vec![3.0, 4.0, 0.0], vec![0.25, -0.5, 1.0]],
            )],
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid inference result failed: {error}"),
        };

        assert_eq!(result.records[0].vector, vec![3.0, 4.0, 0.0]);
        assert_eq!(result.records[1].item_id, "chunk-2");
        assert_eq!(result.metrics.vector_value_count, 6);
    }

    #[test]
    fn rejects_dimension_and_non_finite_runtime_outputs() {
        let request = match BulkEmbeddingRequest::new(
            model(EmbeddingInputKind::Plain),
            policy(1),
            vec![document("chunk-1", "one", None, None)],
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid preparation request failed: {error}"),
        };
        let prepared = match prepare_embedding_batch(request.clone()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid preparation failed: {error}"),
        };
        let Err(dimension_error) = finalize_embedding_batch(
            prepared,
            vec![InferenceBatchOutput::new(0, vec![vec![1.0, 2.0]])],
        ) else {
            unreachable!("wrong dimensions must fail");
        };
        assert_eq!(
            dimension_error.code,
            BulkEmbeddingErrorCode::DimensionMismatch
        );

        let prepared = match prepare_embedding_batch(request) {
            Ok(value) => value,
            Err(error) => unreachable!("valid preparation failed: {error}"),
        };
        let Err(finite_error) = finalize_embedding_batch(
            prepared,
            vec![InferenceBatchOutput::new(0, vec![vec![1.0, f32::NAN, 3.0]])],
        ) else {
            unreachable!("non-finite vector must fail");
        };
        assert_eq!(finite_error.code, BulkEmbeddingErrorCode::NonFiniteVector);
        assert_eq!(finite_error.item_id.as_deref(), Some("chunk-1"));
    }

    #[test]
    fn empty_requests_produce_empty_preparation_and_result() {
        let request = match BulkEmbeddingRequest::new(
            model(EmbeddingInputKind::Plain),
            policy(16),
            Vec::new(),
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("empty request must be valid: {error}"),
        };
        let prepared = match prepare_embedding_batch(request) {
            Ok(value) => value,
            Err(error) => unreachable!("empty preparation failed: {error}"),
        };
        assert!(prepared.batches.is_empty());
        let result = match finalize_embedding_batch(prepared, Vec::new()) {
            Ok(value) => value,
            Err(error) => unreachable!("empty result failed: {error}"),
        };
        assert!(result.records.is_empty());
    }
}
