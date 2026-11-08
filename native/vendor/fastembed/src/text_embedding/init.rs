//! Initialization options for the text embedding models.
//!

use crate::{
    EmbeddingModel, OutputKey, QuantizationMode,
    common::TokenizerFiles,
    init::{HasMaxLength, InitOptionsWithLength},
    pooling::Pooling,
};
use anyhow::{Result, anyhow};
use ort::{
    execution_providers::ExecutionProviderDispatch,
    session::Session,
    value::{DynValue, Tensor},
};
use std::sync::Arc;
use tokenizers::Tokenizer;
use zerocopy::{FromZeros, IntoBytes};

use super::DEFAULT_MAX_LENGTH;

impl HasMaxLength for EmbeddingModel {
    const MAX_LENGTH: usize = DEFAULT_MAX_LENGTH;
}

/// Options for initializing the TextEmbedding model
pub type TextInitOptions = InitOptionsWithLength<EmbeddingModel>;

/// Options for initializing UserDefinedEmbeddingModel
///
/// Model files are held by the UserDefinedEmbeddingModel struct
#[derive(Debug, Clone)]
#[non_exhaustive]
pub struct InitOptionsUserDefined {
    pub execution_providers: Vec<ExecutionProviderDispatch>,
    pub max_length: usize,
    /// Number of intra-op threads for ONNX Runtime. `None` (the default) uses
    /// every available CPU core via `std::thread::available_parallelism`.
    /// Set this to cap CPU usage (e.g. on laptops) at the cost of throughput.
    pub intra_threads: Option<usize>,
}

impl InitOptionsUserDefined {
    pub fn new() -> Self {
        Self {
            ..Default::default()
        }
    }

    pub fn with_execution_providers(
        mut self,
        execution_providers: Vec<ExecutionProviderDispatch>,
    ) -> Self {
        self.execution_providers = execution_providers;
        self
    }

    pub fn with_max_length(mut self, max_length: usize) -> Self {
        self.max_length = max_length;
        self
    }

    /// Set the number of intra-op threads ONNX Runtime uses. By default
    /// (`None`) all available CPU cores are used; capping this limits CPU
    /// usage at the cost of per-inference throughput.
    pub fn with_intra_threads(mut self, intra_threads: usize) -> Self {
        self.intra_threads = Some(intra_threads);
        self
    }
}

impl Default for InitOptionsUserDefined {
    fn default() -> Self {
        Self {
            execution_providers: Default::default(),
            max_length: DEFAULT_MAX_LENGTH,
            intra_threads: None,
        }
    }
}

/// Convert InitOptions to InitOptionsUserDefined
///
/// This is useful for when the user wants to use the same options for both the default and user-defined models
impl From<TextInitOptions> for InitOptionsUserDefined {
    fn from(options: TextInitOptions) -> Self {
        InitOptionsUserDefined {
            execution_providers: options.execution_providers,
            max_length: options.max_length,
            intra_threads: options.intra_threads,
        }
    }
}

/// Struct for "bring your own" embedding models
///
/// The onnx_file and tokenizer_files are expecting the files' bytes
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UserDefinedEmbeddingModel {
    pub onnx_file: Vec<u8>,
    pub external_initializers: Vec<ExternalInitializerFile>,
    pub tokenizer_files: TokenizerFiles,
    pub pooling: Option<Pooling>,
    pub quantization: QuantizationMode,
    pub output_key: Option<OutputKey>,
}

/// An SDK-owned FLOAT initializer whose backing storage remains valid for its OrtValue.
///
/// Metadata is private and is constructed with the ORT tensor in one operation so
/// the adapter can verify registrations against the value that will be committed.
pub struct OwnedFloatTensorInitializer {
    name: String,
    dimensions: Vec<i64>,
    value: Arc<DynValue>,
}

impl OwnedFloatTensorInitializer {
    /// Copy little-endian ONNX FLOAT raw data into initialized caller-owned f32 storage.
    pub fn from_raw_data(name: &str, dimensions: &[i64], raw_data: &[u8]) -> Result<Self> {
        if name.is_empty() || name.as_bytes().contains(&0) {
            return Err(anyhow!("initializer name is empty or invalid"));
        }
        let element_count = checked_float_element_count(dimensions)?;
        let expected_bytes = element_count
            .checked_mul(std::mem::size_of::<f32>())
            .ok_or_else(|| anyhow!("FLOAT initializer byte length overflow"))?;
        if expected_bytes != raw_data.len() {
            return Err(anyhow!(
                "FLOAT initializer data length does not match dimensions"
            ));
        }

        let mut elements = f32::new_vec_zeroed(element_count)
            .map_err(|_| anyhow!("cannot allocate FLOAT initializer storage"))?;
        let target_bytes = elements.as_mut_slice().as_mut_bytes();
        if target_bytes.len() != expected_bytes || target_bytes.len() != raw_data.len() {
            return Err(anyhow!("FLOAT initializer destination length mismatch"));
        }
        #[cfg(target_endian = "little")]
        target_bytes.copy_from_slice(raw_data);
        #[cfg(target_endian = "big")]
        for (element, bytes) in elements.iter_mut().zip(raw_data.chunks_exact(4)) {
            *element = f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
        }
        #[cfg(not(any(target_endian = "little", target_endian = "big")))]
        return Err(anyhow!("unsupported host byte order for ONNX FLOAT data"));

        let tensor = Tensor::<f32>::from_array((dimensions, elements.into_boxed_slice()))?;
        {
            let (actual_dimensions, actual_elements) = tensor.try_extract_tensor::<f32>()?;
            if !actual_dimensions.iter().eq(dimensions.iter())
                || actual_elements.len() != element_count
                || actual_elements
                    .len()
                    .checked_mul(std::mem::size_of::<f32>())
                    != Some(raw_data.len())
            {
                return Err(anyhow!(
                    "ORT FLOAT tensor shape does not match initializer data"
                ));
            }
        }

        Ok(Self {
            name: name.to_owned(),
            dimensions: dimensions.to_vec(),
            value: Arc::new(DynValue::from(tensor.upcast())),
        })
    }

    /// Name attached to the same SDK-owned tensor created by this constructor.
    pub fn name(&self) -> &str {
        &self.name
    }

    /// Ordered dimensions attached to the same SDK-owned tensor.
    pub fn dimensions(&self) -> &[i64] {
        &self.dimensions
    }

    /// ONNX TensorProto.FLOAT type code.
    pub fn data_type(&self) -> i32 {
        1
    }

    pub(crate) fn into_registration(self) -> (String, Arc<DynValue>) {
        (self.name, self.value)
    }
}

fn checked_float_element_count(dimensions: &[i64]) -> Result<usize> {
    dimensions.iter().try_fold(1_usize, |product, dimension| {
        let dimension = usize::try_from(*dimension)
            .map_err(|_| anyhow!("FLOAT initializer has a negative or oversized dimension"))?;
        product
            .checked_mul(dimension)
            .ok_or_else(|| anyhow!("FLOAT initializer element count overflow"))
    })
}

/// An initialized ORT session that is waiting for validated tokenizer files.
///
/// This value cannot perform inference. Call [`finish`](Self::finish) only after the
/// tokenizer assets pass the caller's complete snapshot validation.
pub struct PreparedTextEmbedding {
    pub(crate) session: Session,
    pub(crate) max_length: usize,
    pub(crate) pooling: Option<Pooling>,
    pub(crate) quantization: QuantizationMode,
    pub(crate) output_key: Option<OutputKey>,
}

/// Struct for adding external initializers to "bring your own" embedding models
///
/// The buffer is expecting the data of the external initializer and the file_name
/// must match the one referenced by the model.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExternalInitializerFile {
    pub file_name: String,
    pub buffer: Vec<u8>,
}

impl UserDefinedEmbeddingModel {
    pub fn new(onnx_file: Vec<u8>, tokenizer_files: TokenizerFiles) -> Self {
        Self {
            onnx_file,
            external_initializers: Vec::new(),
            tokenizer_files,
            quantization: QuantizationMode::None,
            pooling: None,
            output_key: None,
        }
    }

    pub fn with_quantization(mut self, quantization: QuantizationMode) -> Self {
        self.quantization = quantization;
        self
    }

    pub fn with_pooling(mut self, pooling: Pooling) -> Self {
        self.pooling = Some(pooling);
        self
    }

    pub fn with_external_initializer(mut self, file_name: String, buffer: Vec<u8>) -> Self {
        self.external_initializers
            .push(ExternalInitializerFile { file_name, buffer });
        self
    }
}

/// Rust representation of the TextEmbedding model
pub struct TextEmbedding {
    pub tokenizer: Tokenizer,
    pub(crate) pooling: Option<Pooling>,
    pub(crate) session: Session,
    pub(crate) need_token_type_ids: bool,
    pub(crate) quantization: QuantizationMode,
    pub(crate) output_key: Option<OutputKey>,
}

#[cfg(test)]
mod tests {
    use super::OwnedFloatTensorInitializer;

    #[test]
    fn owned_initializer_preserves_little_endian_float_bits() -> anyhow::Result<()> {
        let raw_data = [
            0x00, 0x00, 0x00, 0x80, // Negative zero.
            0x01, 0x00, 0xc0, 0x7f, // A quiet NaN payload.
        ];
        let initializer =
            OwnedFloatTensorInitializer::from_raw_data("word_embeddings", &[2], &raw_data)?;
        assert_eq!(initializer.name(), "word_embeddings");
        assert_eq!(initializer.dimensions(), [2]);
        assert_eq!(initializer.data_type(), 1);

        let (_, value) = initializer.into_registration();
        let (_, elements) = value.try_extract_tensor::<f32>()?;
        assert_eq!(elements[0].to_bits(), 0x8000_0000);
        assert_eq!(elements[1].to_bits(), 0x7fc0_0001);
        Ok(())
    }

    #[test]
    fn caller_owned_initializer_is_accepted_by_ort_external_registration() -> anyhow::Result<()> {
        let initializer =
            OwnedFloatTensorInitializer::from_raw_data("word_embeddings", &[2], &[0; 8])?;
        let (name, value) = initializer.into_registration();
        let builder = ort::session::Session::builder()?;

        assert!(
            builder.with_external_initializer(name, value).is_ok(),
            "ORT external initializer registration requires caller-owned tensor data"
        );
        Ok(())
    }

    #[test]
    fn owned_initializer_rejects_bad_shapes_before_tensor_allocation() {
        assert!(OwnedFloatTensorInitializer::from_raw_data("weight", &[-1], &[0; 4]).is_err());
        assert!(
            OwnedFloatTensorInitializer::from_raw_data("weight", &[i64::MAX, 4], &[0; 4]).is_err()
        );
        assert!(OwnedFloatTensorInitializer::from_raw_data("weight", &[2], &[0; 4]).is_err());
        assert!(OwnedFloatTensorInitializer::from_raw_data("weight\0bad", &[1], &[0; 4]).is_err());
    }
}
