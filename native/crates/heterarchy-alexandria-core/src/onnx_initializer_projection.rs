//! Borrowed projection of large embedded FLOAT initializers into ORT-owned tensors.
//!
//! The source model must first pass the unchanged embedded ONNX resource policy.
//! Only large, unambiguous dense FLOAT initializers are projected. Other tensors
//! retain their original protobuf bytes.

use std::error::Error;
use std::fmt::{self, Write as FmtWrite};
use std::str;

use crate::onnx_model_policy::{
    EmbeddedOnnxModelError, FieldValue, read_field_value, read_varint, validate_embedded_onnx_model,
};

const MODEL_GRAPH_FIELD: u64 = 7;
const GRAPH_INITIALIZER_FIELD: u64 = 5;
const TENSOR_DIMENSION_FIELD: u64 = 1;
const TENSOR_DATA_TYPE_FIELD: u64 = 2;
const TENSOR_SEGMENT_FIELD: u64 = 3;
const TENSOR_NAME_FIELD: u64 = 8;
const TENSOR_RAW_DATA_FIELD: u64 = 9;
const TENSOR_EXTERNAL_DATA_FIELD: u64 = 13;
const TENSOR_DATA_LOCATION_FIELD: u64 = 14;
const ONNX_FLOAT_DATA_TYPE: u64 = 1;
const ONNX_EXTERNAL_DATA_LOCATION: u64 = 1;
const MIN_PROJECTED_TENSOR_BYTES: usize = 128;
const PROJECTION_LOCATION_PREFIX: &str = "alexandria_owned_float_";

/// A stable, sanitized failure while deriving or validating a projection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum OnnxInitializerProjectionError {
    /// The original ONNX model did not pass the embedded-resource policy.
    InvalidModel(EmbeddedOnnxModelError),
    /// A malformed protobuf boundary was found while deriving the projection.
    InvalidProtobuf,
    /// A candidate FLOAT initializer had invalid dimensions or inconsistent bytes.
    InvalidInitializer,
    /// An initializer name could not be resolved or was duplicated.
    AmbiguousInitializerName,
    /// The registered value metadata did not exactly match projected tensors.
    RegistrationMismatch,
    /// Bounded projection metadata or protobuf output could not be allocated.
    ResourceExhausted,
}

impl OnnxInitializerProjectionError {
    /// Return a stable diagnostic code without including model data.
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidModel(_) => "ONNX_INITIALIZER_PROJECTION_MODEL_REJECTED",
            Self::InvalidProtobuf => "ONNX_INITIALIZER_PROJECTION_INVALID_PROTOBUF",
            Self::InvalidInitializer => "ONNX_INITIALIZER_PROJECTION_INVALID_TENSOR",
            Self::AmbiguousInitializerName => "ONNX_INITIALIZER_PROJECTION_NAME_AMBIGUOUS",
            Self::RegistrationMismatch => "ONNX_INITIALIZER_PROJECTION_REGISTRATION_MISMATCH",
            Self::ResourceExhausted => "ONNX_INITIALIZER_PROJECTION_RESOURCE_EXHAUSTED",
        }
    }
}

impl fmt::Display for OnnxInitializerProjectionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl Error for OnnxInitializerProjectionError {}

/// One borrowed FLOAT tensor selected by a validated model projection.
#[derive(Debug, Clone)]
pub struct ProjectedFloatInitializer<'a> {
    name: &'a str,
    dimensions: Vec<i64>,
    raw_data: &'a [u8],
}

impl<'a> ProjectedFloatInitializer<'a> {
    /// Return the effective ONNX tensor name after protobuf singular-field merging.
    #[must_use]
    pub const fn name(&self) -> &'a str {
        self.name
    }

    /// Return the ordered ONNX dimensions, including an empty scalar shape.
    #[must_use]
    pub fn dimensions(&self) -> &[i64] {
        &self.dimensions
    }

    /// Return the exact borrowed little-endian FLOAT payload bytes.
    #[must_use]
    pub const fn raw_data(&self) -> &'a [u8] {
        self.raw_data
    }
}

/// The owned, small protobuf and borrowed payloads produced together from one input.
///
/// Fields are private so the projected placeholders and their registered values
/// cannot be assembled independently.
#[derive(Debug)]
pub struct ModelProjection<'a> {
    model_bytes: Vec<u8>,
    initializers: Vec<ProjectedFloatInitializer<'a>>,
}

impl<'a> ModelProjection<'a> {
    /// Return every borrowed initializer represented by the owned protobuf.
    #[must_use]
    pub fn initializers(&self) -> &[ProjectedFloatInitializer<'a>] {
        &self.initializers
    }

    /// Check exact count, names, ordered dimensions and FLOAT type before ORT commit.
    ///
    /// This check intentionally consumes the supplied iterator. Callers derive each
    /// item from its immutable SDK-owned tensor rather than caller-supplied claims.
    ///
    /// # Errors
    ///
    /// Returns an error if count, order, names, dimensions, or type differ.
    pub fn validate_registrations<'r, I>(
        &self,
        registrations: I,
    ) -> Result<(), OnnxInitializerProjectionError>
    where
        I: IntoIterator<Item = InitializerRegistration<'r>>,
    {
        let mut actual = registrations.into_iter();
        for expected in &self.initializers {
            let registered = actual
                .next()
                .ok_or(OnnxInitializerProjectionError::RegistrationMismatch)?;
            if registered.name != expected.name
                || registered.dimensions != expected.dimensions.as_slice()
                || registered.data_type != 1_i32
            {
                return Err(OnnxInitializerProjectionError::RegistrationMismatch);
            }
        }
        if actual.next().is_some() {
            return Err(OnnxInitializerProjectionError::RegistrationMismatch);
        }
        Ok(())
    }

    /// Consume the projection, releasing borrowed tensor descriptions with it.
    #[must_use]
    pub fn into_model_bytes(self) -> Vec<u8> {
        self.model_bytes
    }
}

/// Immutable metadata read from an SDK-owned tensor registration.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InitializerRegistration<'a> {
    /// Exact effective ONNX tensor name.
    pub name: &'a str,
    /// Ordered dimensions reported by the registered tensor.
    pub dimensions: &'a [i64],
    /// ONNX element type identifier (FLOAT is 1).
    pub data_type: i32,
}

struct WireField<'a> {
    number: u64,
    wire_type: u8,
    value: FieldValue<'a>,
    key: &'a [u8],
    encoded: &'a [u8],
}

struct TensorScan<'a> {
    field_index: usize,
    name: TensorName<'a>,
    data_type: Option<u64>,
    dimensions: ScannedDimensions,
    raw_data: Option<&'a [u8]>,
    encoding: TensorEncoding,
    selected_index: Option<usize>,
}

struct TensorName<'a> {
    effective: Option<&'a str>,
    has_invalid_utf8: bool,
}

struct ScannedDimensions {
    values: Vec<i64>,
    valid: bool,
}

#[derive(Default)]
struct TensorEncoding {
    segmented: bool,
    has_typed_data: bool,
    has_unsupported_known_wire: bool,
}

struct GraphScan<'a> {
    fields: Vec<WireField<'a>>,
    tensors: Vec<TensorScan<'a>>,
}

/// Validate and project large embedded dense FLOAT tensor payloads.
///
/// The original ONNX policy is always applied first. An `Ok(None)` means that no
/// initializer qualifies; callers can pass the original bytes to the existing
/// constructor without copying the complete model. Projection errors must not fall
/// through to that constructor.
///
/// Singular protobuf fields use their last valid wire-encoded value. Repeated
/// dimensions concatenate in encoded order. Unsupported data layouts remain
/// embedded byte-for-byte. Every top-level initializer name participates in the
/// duplicate check, including names of ineligible tensors and graph fragments.
///
/// # Errors
///
/// Returns the original embedded-ONNX policy error, invalid candidate metadata,
/// unresolved/duplicate initializer names, or a bounded allocation failure.
pub fn project_embedded_float_initializers(
    input: &[u8],
) -> Result<Option<ModelProjection<'_>>, OnnxInitializerProjectionError> {
    let (model_fields, mut graphs) = scan_model(input)?;
    let Some(initializers) = select_initializers(&mut graphs)? else {
        return Ok(None);
    };
    let model_bytes = rewrite_model(&model_fields, &graphs)?;
    Ok(Some(ModelProjection {
        model_bytes,
        initializers,
    }))
}

fn scan_model(
    input: &[u8],
) -> Result<(Vec<WireField<'_>>, Vec<GraphScan<'_>>), OnnxInitializerProjectionError> {
    validate_embedded_onnx_model(input).map_err(OnnxInitializerProjectionError::InvalidModel)?;
    let model_fields = scan_fields(input)?;
    let mut graphs = Vec::new();
    for field in &model_fields {
        if field.number == MODEL_GRAPH_FIELD && field.wire_type == 2 {
            let FieldValue::Bytes(graph_bytes) = &field.value else {
                return Err(OnnxInitializerProjectionError::InvalidModel(
                    EmbeddedOnnxModelError::InvalidProtobuf,
                ));
            };
            graphs
                .try_reserve(1)
                .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
            graphs.push(scan_graph(graph_bytes)?);
        }
    }
    Ok((model_fields, graphs))
}

fn select_initializers<'a>(
    graphs: &mut [GraphScan<'a>],
) -> Result<Option<Vec<ProjectedFloatInitializer<'a>>>, OnnxInitializerProjectionError> {
    let mut has_unresolved_name = false;
    let initializer_count = graphs
        .iter()
        .try_fold(0_usize, |total, graph| {
            total.checked_add(graph.tensors.len())
        })
        .ok_or(OnnxInitializerProjectionError::ResourceExhausted)?;
    let mut names = Vec::new();
    names
        .try_reserve_exact(initializer_count)
        .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
    let mut has_candidate = false;
    for graph in graphs.iter() {
        for tensor in &graph.tensors {
            if tensor.name.has_invalid_utf8 {
                has_unresolved_name = true;
            }
            if let Some(name) = tensor.name.effective {
                names.push(name);
            }
            has_candidate |= tensor.is_candidate();
        }
    }
    if !has_candidate {
        return Ok(None);
    }
    names.sort_unstable();
    let has_duplicate_name = names.windows(2).any(|pair| pair[0] == pair[1]);
    if has_unresolved_name {
        return Err(OnnxInitializerProjectionError::AmbiguousInitializerName);
    }
    if has_duplicate_name {
        return Err(OnnxInitializerProjectionError::AmbiguousInitializerName);
    }

    let mut initializers = Vec::new();
    for graph in graphs.iter_mut() {
        for tensor in &mut graph.tensors {
            if !tensor.is_candidate() {
                continue;
            }
            if !tensor.dimensions.valid {
                return Err(OnnxInitializerProjectionError::InvalidInitializer);
            }
            let name = tensor
                .name
                .effective
                .filter(|name| !name.is_empty() && !name.contains('\0'))
                .ok_or(OnnxInitializerProjectionError::AmbiguousInitializerName)?;
            let raw_data = tensor
                .raw_data
                .ok_or(OnnxInitializerProjectionError::InvalidInitializer)?;
            validate_float_length(&tensor.dimensions.values, raw_data.len())?;

            initializers
                .try_reserve(1)
                .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
            tensor.selected_index = Some(initializers.len());
            let mut owned_dimensions = Vec::new();
            owned_dimensions
                .try_reserve_exact(tensor.dimensions.values.len())
                .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
            owned_dimensions.extend_from_slice(&tensor.dimensions.values);
            initializers.push(ProjectedFloatInitializer {
                name,
                dimensions: owned_dimensions,
                raw_data,
            });
        }
    }

    if initializers.is_empty() {
        return Ok(None);
    }

    Ok(Some(initializers))
}

fn rewrite_model(
    model_fields: &[WireField<'_>],
    graphs: &[GraphScan<'_>],
) -> Result<Vec<u8>, OnnxInitializerProjectionError> {
    let mut projected_model = Vec::new();
    let mut graph_index = 0;
    for field in model_fields {
        if field.number == MODEL_GRAPH_FIELD && field.wire_type == 2 {
            let Some(graph) = graphs.get(graph_index) else {
                return Err(invalid_protobuf());
            };
            graph_index = graph_index
                .checked_add(1)
                .ok_or(OnnxInitializerProjectionError::ResourceExhausted)?;
            let rewritten = rewrite_graph(graph)?;
            append_length_field_with_key(&mut projected_model, field.key, &rewritten)?;
        } else {
            append(&mut projected_model, field.encoded)?;
        }
    }

    Ok(projected_model)
}

impl TensorScan<'_> {
    fn could_be_large_float(&self) -> bool {
        self.data_type == Some(ONNX_FLOAT_DATA_TYPE)
            && self
                .raw_data
                .is_some_and(|raw_data| raw_data.len() > MIN_PROJECTED_TENSOR_BYTES - 1)
    }

    fn is_candidate(&self) -> bool {
        self.could_be_large_float()
            && !self.encoding.segmented
            && !self.encoding.has_typed_data
            && !self.encoding.has_unsupported_known_wire
    }
}

fn scan_graph(bytes: &[u8]) -> Result<GraphScan<'_>, OnnxInitializerProjectionError> {
    let fields = scan_fields(bytes)?;
    let mut tensors = Vec::new();
    for (field_index, field) in fields.iter().enumerate() {
        if field.number != GRAPH_INITIALIZER_FIELD || field.wire_type != 2 {
            continue;
        }
        let FieldValue::Bytes(tensor_bytes) = &field.value else {
            return Err(invalid_protobuf());
        };
        tensors
            .try_reserve(1)
            .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
        tensors.push(scan_tensor(field_index, tensor_bytes)?);
    }
    Ok(GraphScan { fields, tensors })
}

fn scan_tensor(
    field_index: usize,
    bytes: &[u8],
) -> Result<TensorScan<'_>, OnnxInitializerProjectionError> {
    let fields = scan_fields(bytes)?;
    let mut name = TensorName {
        effective: Some(""),
        has_invalid_utf8: false,
    };
    let mut data_type = None;
    let mut dimensions = ScannedDimensions {
        values: Vec::new(),
        valid: true,
    };
    let mut raw_data = None;
    let mut encoding = TensorEncoding::default();

    for field in &fields {
        if tensor_field_wire_support(field.number, field.wire_type) == Some(false) {
            encoding.has_unsupported_known_wire = true;
            continue;
        }
        match (field.number, field.wire_type, &field.value) {
            (TENSOR_NAME_FIELD, 2, FieldValue::Bytes(value)) => {
                let Ok(value) = str::from_utf8(value) else {
                    name.effective = None;
                    name.has_invalid_utf8 = true;
                    continue;
                };
                name.effective = Some(value);
            }
            (TENSOR_DATA_TYPE_FIELD, 0, FieldValue::Varint(value)) => {
                data_type = Some(*value);
            }
            (TENSOR_DIMENSION_FIELD, 0, FieldValue::Varint(value)) => {
                append_dimension(*value, &mut dimensions)?;
            }
            (TENSOR_DIMENSION_FIELD, 2, FieldValue::Bytes(packed)) => {
                parse_packed_dimensions(packed, &mut dimensions)?;
            }
            (TENSOR_RAW_DATA_FIELD, 2, FieldValue::Bytes(value)) => raw_data = Some(*value),
            (TENSOR_SEGMENT_FIELD, 2, FieldValue::Bytes(_)) => encoding.segmented = true,
            (4, 2 | 5, _) | (5 | 7 | 11, 0 | 2, _) | (6, 2, _) | (10, 1 | 2, _) => {
                encoding.has_typed_data = true;
            }
            _ => {}
        }
    }

    Ok(TensorScan {
        field_index,
        name,
        data_type,
        dimensions,
        raw_data,
        encoding,
        selected_index: None,
    })
}

fn tensor_field_wire_support(field_number: u64, wire_type: u8) -> Option<bool> {
    let supported = match field_number {
        TENSOR_DIMENSION_FIELD => matches!(wire_type, 0 | 2),
        TENSOR_DATA_TYPE_FIELD => wire_type == 0,
        TENSOR_SEGMENT_FIELD => wire_type == 2,
        4 => matches!(wire_type, 2 | 5),
        5 | 7 | 11 => matches!(wire_type, 0 | 2),
        6 | TENSOR_NAME_FIELD | TENSOR_RAW_DATA_FIELD | TENSOR_EXTERNAL_DATA_FIELD => {
            wire_type == 2
        }
        10 => matches!(wire_type, 1 | 2),
        TENSOR_DATA_LOCATION_FIELD => wire_type == 0,
        _ => return None,
    };
    Some(supported)
}

fn append_dimension(
    value: u64,
    dimensions: &mut ScannedDimensions,
) -> Result<(), OnnxInitializerProjectionError> {
    if !dimensions.valid {
        return Ok(());
    }
    let Ok(value) = i64::try_from(value) else {
        dimensions.valid = false;
        return Ok(());
    };
    if value < 0 {
        dimensions.valid = false;
        return Ok(());
    }
    dimensions
        .values
        .try_reserve(1)
        .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
    dimensions.values.push(value);
    Ok(())
}

fn parse_packed_dimensions(
    packed: &[u8],
    dimensions: &mut ScannedDimensions,
) -> Result<(), OnnxInitializerProjectionError> {
    let mut offset = 0;
    while offset < packed.len() {
        let value = read_varint(packed, &mut offset).map_err(map_wire_error)?;
        append_dimension(value, dimensions)?;
    }
    Ok(())
}

fn validate_float_length(
    dimensions: &[i64],
    raw_length: usize,
) -> Result<(), OnnxInitializerProjectionError> {
    let mut element_count = 1_usize;
    for dimension in dimensions {
        let dimension = usize::try_from(*dimension)
            .map_err(|_| OnnxInitializerProjectionError::InvalidInitializer)?;
        element_count = element_count
            .checked_mul(dimension)
            .ok_or(OnnxInitializerProjectionError::InvalidInitializer)?;
    }
    let byte_count = element_count
        .checked_mul(std::mem::size_of::<f32>())
        .ok_or(OnnxInitializerProjectionError::InvalidInitializer)?;
    if byte_count != raw_length {
        return Err(OnnxInitializerProjectionError::InvalidInitializer);
    }
    Ok(())
}

fn rewrite_graph(graph: &GraphScan<'_>) -> Result<Vec<u8>, OnnxInitializerProjectionError> {
    let mut rewritten = Vec::new();
    let mut tensor_index = 0;
    for (field_index, field) in graph.fields.iter().enumerate() {
        if field.number == GRAPH_INITIALIZER_FIELD && field.wire_type == 2 {
            let tensor = graph
                .tensors
                .get(tensor_index)
                .ok_or_else(invalid_protobuf)?;
            tensor_index += 1;
            if tensor.field_index != field_index {
                return Err(invalid_protobuf());
            }
            if let Some(index) = tensor.selected_index {
                let FieldValue::Bytes(tensor_bytes) = &field.value else {
                    return Err(invalid_protobuf());
                };
                let raw_length = tensor
                    .raw_data
                    .ok_or(OnnxInitializerProjectionError::InvalidInitializer)?
                    .len();
                let tensor_bytes = rewrite_tensor(tensor_bytes, index, raw_length)?;
                append_length_field_with_key(&mut rewritten, field.key, &tensor_bytes)?;
            } else {
                append(&mut rewritten, field.encoded)?;
            }
        } else {
            append(&mut rewritten, field.encoded)?;
        }
    }
    Ok(rewritten)
}

fn rewrite_tensor(
    tensor: &[u8],
    initializer_index: usize,
    raw_length: usize,
) -> Result<Vec<u8>, OnnxInitializerProjectionError> {
    let fields = scan_fields(tensor)?;
    let mut rewritten = Vec::new();
    for field in &fields {
        if (field.number == TENSOR_RAW_DATA_FIELD && field.wire_type == 2)
            || (field.number == TENSOR_DATA_LOCATION_FIELD && field.wire_type == 0)
        {
            continue;
        }
        append(&mut rewritten, field.encoded)?;
    }

    let location = projection_location(initializer_index)?;
    append_external_data_entry(&mut rewritten, "location", &location)?;
    append_external_data_entry(&mut rewritten, "offset", "0")?;
    append_external_data_entry(&mut rewritten, "length", &usize_decimal(raw_length)?)?;
    append_varint_field(
        &mut rewritten,
        TENSOR_DATA_LOCATION_FIELD,
        ONNX_EXTERNAL_DATA_LOCATION,
    )?;
    Ok(rewritten)
}

fn projection_location(index: usize) -> Result<String, OnnxInitializerProjectionError> {
    let capacity = PROJECTION_LOCATION_PREFIX
        .len()
        .checked_add(usize_decimal_length(index))
        .ok_or(OnnxInitializerProjectionError::ResourceExhausted)?;
    let mut location = String::new();
    location
        .try_reserve_exact(capacity)
        .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
    location.push_str(PROJECTION_LOCATION_PREFIX);
    write!(location, "{index}").map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
    Ok(location)
}

fn usize_decimal(value: usize) -> Result<String, OnnxInitializerProjectionError> {
    let mut output = String::new();
    output
        .try_reserve_exact(usize_decimal_length(value))
        .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
    write!(output, "{value}").map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
    Ok(output)
}

fn usize_decimal_length(mut value: usize) -> usize {
    let mut length = 1;
    while value >= 10 {
        value /= 10;
        length += 1;
    }
    length
}

fn append_external_data_entry(
    tensor: &mut Vec<u8>,
    key: &str,
    value: &str,
) -> Result<(), OnnxInitializerProjectionError> {
    let mut entry = Vec::new();
    append_bytes_field(&mut entry, 1, key.as_bytes())?;
    append_bytes_field(&mut entry, 2, value.as_bytes())?;
    append_bytes_field(tensor, TENSOR_EXTERNAL_DATA_FIELD, &entry)
}

fn scan_fields(bytes: &[u8]) -> Result<Vec<WireField<'_>>, OnnxInitializerProjectionError> {
    let mut fields = Vec::new();
    let mut offset = 0;
    while offset < bytes.len() {
        let start = offset;
        let key = read_varint(bytes, &mut offset).map_err(map_wire_error)?;
        let number = key >> 3;
        let wire_type = u8::try_from(key & 7).map_err(|_| invalid_protobuf())?;
        let key_bytes = bytes.get(start..offset).ok_or_else(invalid_protobuf)?;
        let value = read_field_value(bytes, &mut offset, wire_type).map_err(map_wire_error)?;
        let encoded = bytes.get(start..offset).ok_or_else(invalid_protobuf)?;
        fields
            .try_reserve(1)
            .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
        fields.push(WireField {
            number,
            wire_type,
            value,
            key: key_bytes,
            encoded,
        });
    }
    Ok(fields)
}

fn append(out: &mut Vec<u8>, bytes: &[u8]) -> Result<(), OnnxInitializerProjectionError> {
    out.try_reserve(bytes.len())
        .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
    out.extend_from_slice(bytes);
    Ok(())
}

fn append_varint_field(
    out: &mut Vec<u8>,
    field_number: u64,
    value: u64,
) -> Result<(), OnnxInitializerProjectionError> {
    append_varint(out, field_number << 3)?;
    append_varint(out, value)
}

fn append_bytes_field(
    out: &mut Vec<u8>,
    field_number: u64,
    value: &[u8],
) -> Result<(), OnnxInitializerProjectionError> {
    append_varint(out, (field_number << 3) | 2)?;
    append_varint(
        out,
        u64::try_from(value.len())
            .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?,
    )?;
    append(out, value)
}

fn append_length_field_with_key(
    out: &mut Vec<u8>,
    original_key: &[u8],
    value: &[u8],
) -> Result<(), OnnxInitializerProjectionError> {
    append(out, original_key)?;
    append_varint(
        out,
        u64::try_from(value.len())
            .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?,
    )?;
    append(out, value)
}

fn append_varint(out: &mut Vec<u8>, mut value: u64) -> Result<(), OnnxInitializerProjectionError> {
    out.try_reserve(10)
        .map_err(|_| OnnxInitializerProjectionError::ResourceExhausted)?;
    while value >= 0x80 {
        out.push((value.to_le_bytes()[0] & 0x7f) | 0x80);
        value >>= 7;
    }
    out.push(value.to_le_bytes()[0]);
    Ok(())
}

fn map_wire_error(error: EmbeddedOnnxModelError) -> OnnxInitializerProjectionError {
    match error {
        EmbeddedOnnxModelError::ResourceExhausted => {
            OnnxInitializerProjectionError::ResourceExhausted
        }
        _ => OnnxInitializerProjectionError::InvalidProtobuf,
    }
}

fn invalid_protobuf() -> OnnxInitializerProjectionError {
    OnnxInitializerProjectionError::InvalidProtobuf
}

#[cfg(test)]
mod tests {
    use super::{
        GRAPH_INITIALIZER_FIELD, InitializerRegistration, MODEL_GRAPH_FIELD, ModelProjection,
        OnnxInitializerProjectionError, TENSOR_DATA_LOCATION_FIELD, TENSOR_EXTERNAL_DATA_FIELD,
        TENSOR_RAW_DATA_FIELD, project_embedded_float_initializers, scan_fields,
    };
    use crate::onnx_model_policy::{FieldValue, validate_embedded_onnx_model};

    fn put_varint(mut value: u64, output: &mut Vec<u8>) {
        while value >= 0x80 {
            output.push((value.to_le_bytes()[0] & 0x7f) | 0x80);
            value >>= 7;
        }
        output.push(value.to_le_bytes()[0]);
    }

    fn varint_field(number: u64, value: u64) -> Vec<u8> {
        let mut output = Vec::new();
        put_varint(number << 3, &mut output);
        put_varint(value, &mut output);
        output
    }

    fn bytes_field(number: u64, value: &[u8]) -> Vec<u8> {
        let mut output = Vec::new();
        put_varint((number << 3) | 2, &mut output);
        let Ok(length) = u64::try_from(value.len()) else {
            return output;
        };
        put_varint(length, &mut output);
        output.extend_from_slice(value);
        output
    }

    fn packed_i64_field(number: u64, values: &[u64]) -> Vec<u8> {
        let mut packed = Vec::new();
        for value in values {
            put_varint(*value, &mut packed);
        }
        bytes_field(number, &packed)
    }

    fn tensor(name: &[u8], dimensions: &[i64], data_type: u64, raw_data: &[u8]) -> Vec<u8> {
        let mut bytes = Vec::new();
        for dimension in dimensions {
            let mut field = Vec::new();
            put_varint(1 << 3, &mut field);
            let Ok(encoded_dimension) = u64::try_from(*dimension) else {
                return bytes;
            };
            put_varint(encoded_dimension, &mut field);
            bytes.extend_from_slice(&field);
        }
        bytes.extend_from_slice(&varint_field(2, data_type));
        bytes.extend_from_slice(&bytes_field(8, name));
        bytes.extend_from_slice(&bytes_field(9, raw_data));
        bytes
    }

    fn model(graphs: &[Vec<u8>]) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&varint_field(1, 13));
        for graph in graphs {
            bytes.extend_from_slice(&bytes_field(7, graph));
        }
        bytes
    }

    fn graph(initializers: &[Vec<u8>]) -> Vec<u8> {
        let mut bytes = Vec::new();
        for initializer in initializers {
            bytes.extend_from_slice(&bytes_field(5, initializer));
        }
        bytes
    }

    fn projection(
        bytes: &[u8],
    ) -> Result<Option<ModelProjection<'_>>, OnnxInitializerProjectionError> {
        project_embedded_float_initializers(bytes)
    }

    fn encoded_field(bytes: &[u8], number: u64) -> Option<&[u8]> {
        scan_fields(bytes)
            .ok()?
            .into_iter()
            .find(|field| field.number == number)
            .map(|field| field.encoded)
    }

    fn message_field(bytes: &[u8], number: u64) -> Option<&[u8]> {
        scan_fields(bytes)
            .ok()?
            .into_iter()
            .find(|field| field.number == number)
            .and_then(|field| match field.value {
                FieldValue::Bytes(value) => Some(value),
                FieldValue::Varint(_) | FieldValue::Other => None,
            })
    }

    fn graph_initializer_at(
        model_bytes: &[u8],
        graph_index: usize,
        initializer_index: usize,
    ) -> Option<&[u8]> {
        let model_fields = scan_fields(model_bytes).ok()?;
        let graph_bytes = model_fields
            .iter()
            .filter_map(|field| match &field.value {
                FieldValue::Bytes(graph) if field.number == 7 => Some(*graph),
                FieldValue::Bytes(_) | FieldValue::Varint(_) | FieldValue::Other => None,
            })
            .nth(graph_index)?;
        let graph_fields = scan_fields(graph_bytes).ok()?;
        graph_fields
            .iter()
            .filter_map(|field| match &field.value {
                FieldValue::Bytes(initializer) if field.number == GRAPH_INITIALIZER_FIELD => {
                    Some(*initializer)
                }
                FieldValue::Bytes(_) | FieldValue::Varint(_) | FieldValue::Other => None,
            })
            .nth(initializer_index)
    }

    fn projection_preserves_unknown_fields(source: &[u8], projected: &[u8]) -> Option<bool> {
        let source_tensor = message_field(message_field(source, 7)?, 5)?;
        let projected_tensor = message_field(message_field(projected, 7)?, 5)?;
        Some(
            encoded_field(source, 120) == encoded_field(projected, 120)
                && encoded_field(source_tensor, 100) == encoded_field(projected_tensor, 100),
        )
    }

    fn projection_has_expected_external_initializer(projected: &[u8]) -> Option<bool> {
        let model_fields = scan_fields(projected).ok()?;
        let mut found = false;
        for graph in model_fields.iter().filter_map(|field| match &field.value {
            FieldValue::Bytes(graph) if field.number == MODEL_GRAPH_FIELD => Some(*graph),
            FieldValue::Bytes(_) | FieldValue::Varint(_) | FieldValue::Other => None,
        }) {
            let graph_fields = scan_fields(graph).ok()?;
            for tensor in graph_fields.iter().filter_map(|field| match &field.value {
                FieldValue::Bytes(tensor) if field.number == GRAPH_INITIALIZER_FIELD => {
                    Some(*tensor)
                }
                FieldValue::Bytes(_) | FieldValue::Varint(_) | FieldValue::Other => None,
            }) {
                let fields = scan_fields(tensor).ok()?;
                if fields
                    .iter()
                    .any(|field| field.number == TENSOR_EXTERNAL_DATA_FIELD)
                {
                    found = true;
                    if fields
                        .iter()
                        .any(|field| field.number == TENSOR_RAW_DATA_FIELD && field.wire_type == 2)
                        || !fields.iter().any(|field| {
                            field.number == TENSOR_DATA_LOCATION_FIELD
                                && matches!(field.value, FieldValue::Varint(1))
                        })
                    {
                        return Some(false);
                    }
                }
            }
        }
        Some(found)
    }

    #[test]
    fn projects_large_float_payload_and_preserves_untouched_model_fields() {
        let mut raw = vec![0_u8; 128];
        raw[0..4].copy_from_slice(&(-0.0_f32).to_le_bytes());
        raw[4..8].copy_from_slice(&f32::from_bits(0x7fc1_2345).to_le_bytes());
        let mut tensor = tensor(b"weights", &[32], 1, &raw);
        // An unknown TensorProto field must stay byte-for-byte unchanged.
        tensor.extend_from_slice(&bytes_field(100, b"unknown-tensor-field"));
        let graph = graph(&[tensor]);
        let mut source = model(&[graph]);
        // An unknown ModelProto field must also stay byte-for-byte unchanged.
        source.extend_from_slice(&bytes_field(120, b"unknown-model-field"));

        let Ok(Some(projection)) = projection(&source) else {
            unreachable!("large unambiguous FLOAT tensor must project");
        };
        assert_eq!(projection.initializers().len(), 1);
        assert_eq!(projection.initializers()[0].name(), "weights");
        assert_eq!(projection.initializers()[0].dimensions(), [32]);
        assert_eq!(projection.initializers()[0].raw_data(), raw.as_slice());
        if let Err(error) = projection.validate_registrations([InitializerRegistration {
            name: "weights",
            dimensions: &[32],
            data_type: 1,
        }]) {
            unreachable!("matching SDK-owned initializer must pass: {error}");
        }

        let projected = projection.into_model_bytes();
        if let Err(error) = validate_embedded_onnx_model(&source) {
            unreachable!("original embedded-resource model must pass unchanged policy: {error}");
        }
        assert_eq!(
            projection_has_expected_external_initializer(&projected),
            Some(true)
        );
        assert_eq!(
            projection_preserves_unknown_fields(&source, &projected),
            Some(true)
        );
    }

    #[test]
    fn protobuf_last_singular_values_and_packed_dimensions_are_used() {
        let mut raw = vec![0_u8; 128];
        raw[0..4].copy_from_slice(&(-0.0_f32).to_le_bytes());
        raw[4..8].copy_from_slice(&f32::from_bits(0x7fc0_1234).to_le_bytes());
        let mut fields = Vec::new();
        fields.extend_from_slice(&varint_field(1, 4));
        fields.extend_from_slice(&varint_field(2, 7));
        fields.extend_from_slice(&varint_field(2, 1));
        fields.extend_from_slice(&bytes_field(8, b"old-name"));
        fields.extend_from_slice(&bytes_field(8, b"last-name"));
        fields.extend_from_slice(&bytes_field(9, &[1, 2, 3, 4]));
        fields.extend_from_slice(&packed_i64_field(1, &[8]));
        fields.extend_from_slice(&bytes_field(9, &raw));
        let onnx_tensor = fields;
        let source = model(&[graph(&[onnx_tensor])]);

        let Ok(Some(projection)) = projection(&source) else {
            unreachable!("effective FLOAT tensor must project");
        };
        let initializer = &projection.initializers()[0];
        assert_eq!(initializer.name(), "last-name");
        assert_eq!(initializer.dimensions(), [4, 8]);
        assert_eq!(initializer.raw_data(), raw.as_slice());
    }

    #[test]
    fn duplicate_names_include_ineligible_tensors_and_graph_fragments() {
        let large = tensor(b"duplicate", &[32], 1, &[0_u8; 128]);
        let small = tensor(b"duplicate", &[1], 1, &[0_u8; 4]);
        let source = model(&[graph(&[large]), graph(&[small])]);
        assert_eq!(
            projection(&source).err(),
            Some(OnnxInitializerProjectionError::AmbiguousInitializerName)
        );

        let float_duplicate = tensor(b"duplicate", &[32], 1, &[0_u8; 128]);
        let non_float_duplicate = tensor(b"duplicate", &[32], 7, &[0_u8; 128]);
        let source = model(&[graph(&[float_duplicate, non_float_duplicate])]);
        assert_eq!(
            projection(&source).err(),
            Some(OnnxInitializerProjectionError::AmbiguousInitializerName)
        );
    }

    #[test]
    fn unsupported_known_wire_encoding_stays_embedded_when_another_graph_projects() {
        let mut malformed = tensor(b"malformed-wire-data", &[32], 1, &[0_u8; 128]);
        // Tensor.raw_data is bytes, so this varint wire form is an unknown,
        // unsupported duplicate encoding of a known field and must not cause the
        // valid bytes field to be projected away.
        malformed.extend_from_slice(&varint_field(TENSOR_RAW_DATA_FIELD, 128));
        let source = model(&[
            graph(&[malformed]),
            graph(&[tensor(b"valid", &[32], 1, &[0_u8; 128])]),
        ]);

        let Ok(Some(projected)) = projection(&source) else {
            unreachable!("the valid FLOAT tensor in the second graph must project");
        };
        assert_eq!(projected.initializers().len(), 1);
        assert_eq!(projected.initializers()[0].name(), "valid");
        let projected_bytes = projected.into_model_bytes();
        assert_eq!(
            graph_initializer_at(&source, 0, 0),
            graph_initializer_at(&projected_bytes, 0, 0),
            "the ineligible tensor must retain its exact original encoding"
        );
        assert!(projection_has_expected_external_initializer(&projected_bytes).unwrap_or(false));
    }

    #[test]
    fn unsupported_mixed_segmented_and_small_initializers_remain_embedded() {
        let small = tensor(b"small", &[1], 1, &[0_u8; 4]);
        let non_float = tensor(b"int64", &[16], 7, &[0_u8; 128]);
        let mut mixed = tensor(b"mixed", &[32], 1, &[0_u8; 128]);
        mixed.extend_from_slice(&bytes_field(4, &[0, 0, 0, 0]));
        let mut segmented = tensor(b"segmented", &[32], 1, &[0_u8; 128]);
        let mut segment = varint_field(1, 0);
        segment.extend_from_slice(&varint_field(2, 32));
        segmented.extend_from_slice(&bytes_field(3, &segment));
        let source = model(&[graph(&[small, non_float, mixed, segmented])]);
        let Ok(None) = projection(&source) else {
            unreachable!("unsupported layouts stay embedded");
        };
    }

    #[test]
    fn malformed_shape_and_unresolved_names_fail_only_when_projecting() {
        let malformed_shape = tensor(b"bad-shape", &[127], 1, &[0_u8; 128]);
        let source = model(&[graph(&[malformed_shape])]);
        assert_eq!(
            projection(&source).err(),
            Some(OnnxInitializerProjectionError::InvalidInitializer)
        );

        let mut negative_dimension = tensor(b"negative", &[32], 1, &[0_u8; 128]);
        let negative_field = varint_field(1, u64::MAX);
        negative_dimension.splice(0..0, negative_field);
        let source = model(&[graph(&[negative_dimension])]);
        assert_eq!(
            projection(&source).err(),
            Some(OnnxInitializerProjectionError::InvalidInitializer)
        );

        let invalid_name = tensor(&[0xff], &[32], 1, &[0_u8; 128]);
        let projected_elsewhere = tensor(b"valid", &[32], 1, &[0_u8; 128]);
        let source = model(&[graph(&[invalid_name, projected_elsewhere])]);
        assert_eq!(
            projection(&source).err(),
            Some(OnnxInitializerProjectionError::AmbiguousInitializerName)
        );

        let nul_name = tensor(b"valid\0name", &[32], 1, &[0_u8; 128]);
        assert_eq!(
            projection(&model(&[graph(&[nul_name])])).err(),
            Some(OnnxInitializerProjectionError::AmbiguousInitializerName)
        );

        let scalar = tensor(b"scalar", &[], 1, &[0_u8; 128]);
        assert_eq!(
            projection(&model(&[graph(&[scalar])])).err(),
            Some(OnnxInitializerProjectionError::InvalidInitializer)
        );
    }

    #[test]
    fn original_external_data_gate_runs_before_projection() {
        let mut external = tensor(b"external", &[32], 1, &[0_u8; 128]);
        external.extend_from_slice(&bytes_field(13, b"original external reference"));
        let source = model(&[graph(&[external])]);
        let Err(error) = projection(&source) else {
            unreachable!("original external data remains rejected");
        };
        assert_eq!(
            error,
            OnnxInitializerProjectionError::InvalidModel(
                crate::onnx_model_policy::EmbeddedOnnxModelError::ExternalTensorData
            )
        );
    }

    #[test]
    fn registration_count_name_dimensions_and_type_must_all_match() {
        let source = model(&[graph(&[tensor(b"weights", &[32], 1, &[0_u8; 128])])]);
        let Ok(Some(projection)) = projection(&source) else {
            unreachable!("large FLOAT source is valid and projected");
        };
        for actual in [
            vec![],
            vec![InitializerRegistration {
                name: "wrong",
                dimensions: &[32],
                data_type: 1,
            }],
            vec![InitializerRegistration {
                name: "weights",
                dimensions: &[4, 8],
                data_type: 1,
            }],
            vec![InitializerRegistration {
                name: "weights",
                dimensions: &[32],
                data_type: 7,
            }],
            {
                let registration = InitializerRegistration {
                    name: "weights",
                    dimensions: &[32],
                    data_type: 1,
                };
                vec![registration, registration]
            },
        ] {
            assert_eq!(
                projection.validate_registrations(actual),
                Err(OnnxInitializerProjectionError::RegistrationMismatch)
            );
        }
    }
}
