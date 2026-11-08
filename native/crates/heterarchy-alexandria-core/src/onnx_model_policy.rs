//! Admission checks for the pinned, embedded ONNX protobuf model format.
//!
//! This walks only the ONNX v1.22.0 messages and fields whose contents can
//! select external tensor data or the ORT `EPContext` operator. It is not a
//! general ONNX validator or a sandbox for arbitrary ONNX Runtime operators.

use std::error::Error;
use std::fmt;

/// A stable, sanitized reason an embedded ONNX model was not admitted.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum EmbeddedOnnxModelError {
    /// The protobuf wire encoding is malformed or an inspected field has the wrong wire type.
    InvalidProtobuf,
    /// The ORT `FlatBuffer` file identifier was found instead of an ONNX protobuf.
    OrtFlatbufferNotSupported,
    /// No ONNX IR version was present.
    MissingIrVersion,
    /// An ONNX IR version outside the pinned range was present.
    UnsupportedIrVersion,
    /// No model graph was present.
    MissingGraph,
    /// A tensor declared external data.
    ExternalTensorData,
    /// A tensor selected a non-default data location.
    ExternalTensorLocation,
    /// A node selected the ORT `EPContext` operator.
    EpContextNode,
    /// The validator could not reserve memory for its iterative traversal frames.
    ResourceExhausted,
}

impl EmbeddedOnnxModelError {
    /// Return the stable, sanitized diagnostic code for this error.
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidProtobuf => "EMBEDDED_ONNX_INVALID_PROTOBUF",
            Self::OrtFlatbufferNotSupported => "EMBEDDED_ONNX_ORT_FLATBUFFER_UNSUPPORTED",
            Self::MissingIrVersion => "EMBEDDED_ONNX_IR_VERSION_MISSING",
            Self::UnsupportedIrVersion => "EMBEDDED_ONNX_IR_VERSION_UNSUPPORTED",
            Self::MissingGraph => "EMBEDDED_ONNX_GRAPH_MISSING",
            Self::ExternalTensorData => "EMBEDDED_ONNX_EXTERNAL_TENSOR_DATA",
            Self::ExternalTensorLocation => "EMBEDDED_ONNX_EXTERNAL_TENSOR_LOCATION",
            Self::EpContextNode => "EMBEDDED_ONNX_EPCONTEXT_NODE",
            Self::ResourceExhausted => "EMBEDDED_ONNX_VALIDATOR_RESOURCE_EXHAUSTED",
        }
    }
}

impl fmt::Display for EmbeddedOnnxModelError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl Error for EmbeddedOnnxModelError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum MessageKind {
    Model,
    TrainingInfo,
    Graph,
    Node,
    Attribute,
    Tensor,
    SparseTensor,
    Function,
}

struct Frame<'a> {
    bytes: &'a [u8],
    offset: usize,
    kind: MessageKind,
}

pub(crate) enum FieldValue<'a> {
    Varint(u64),
    Bytes(&'a [u8]),
    Other,
}

/// Admit only embedded ONNX protobuf models with no external tensor references
/// and no ORT `EPContext` nodes along the reviewed ONNX message paths.
///
/// The schema is pinned to ONNX v1.22.0 / IR 1 through 13. The iterative walk
/// retains borrowed protobuf slices, skips tensor payload bytes without
/// inspecting them, and has no arbitrary nesting-depth limit.
///
/// # Errors
///
/// Returns a stable, sanitized [`EmbeddedOnnxModelError`] when the input is
/// malformed, uses an unsupported format or IR version, omits required model
/// metadata, references external tensor data, contains an `EPContext` node, or
/// cannot reserve traversal-frame memory.
pub fn validate_embedded_onnx_model(input: &[u8]) -> Result<(), EmbeddedOnnxModelError> {
    if input
        .get(4..8)
        .is_some_and(|identifier| identifier == b"ORTM".as_slice())
    {
        return Err(EmbeddedOnnxModelError::OrtFlatbufferNotSupported);
    }

    let mut frames = Vec::new();
    push_frame(
        &mut frames,
        Frame {
            bytes: input,
            offset: 0,
            kind: MessageKind::Model,
        },
    )?;

    let mut has_ir_version = false;
    let mut has_graph = false;

    while !frames.is_empty() {
        if frames
            .last()
            .is_some_and(|frame| frame.offset == frame.bytes.len())
        {
            frames.pop();
            continue;
        }

        let mut child = None;
        {
            let Some(frame) = frames.last_mut() else {
                return Err(EmbeddedOnnxModelError::InvalidProtobuf);
            };

            let key = read_varint(frame.bytes, &mut frame.offset)?;
            let field_number = key >> 3;
            if field_number == 0 || field_number > MAX_FIELD_NUMBER {
                return Err(EmbeddedOnnxModelError::InvalidProtobuf);
            }
            let wire_type =
                u8::try_from(key & 0x07).map_err(|_| EmbeddedOnnxModelError::InvalidProtobuf)?;

            // external_data is rejected by field presence, even if an encoder
            // supplied a nonstandard wire type for this inspected field.
            if frame.kind == MessageKind::Tensor && field_number == 13 {
                return Err(EmbeddedOnnxModelError::ExternalTensorData);
            }

            if let Some(expected_wire_type) = expected_wire_type(frame.kind, field_number)
                && wire_type != expected_wire_type
            {
                return Err(EmbeddedOnnxModelError::InvalidProtobuf);
            }

            let value = read_field_value(frame.bytes, &mut frame.offset, wire_type)?;
            match value {
                FieldValue::Varint(version)
                    if frame.kind == MessageKind::Model && field_number == 1 =>
                {
                    if !(1..=13).contains(&version) {
                        return Err(EmbeddedOnnxModelError::UnsupportedIrVersion);
                    }
                    has_ir_version = true;
                }
                FieldValue::Varint(location)
                    if frame.kind == MessageKind::Tensor && field_number == 14 && location != 0 =>
                {
                    return Err(EmbeddedOnnxModelError::ExternalTensorLocation);
                }
                FieldValue::Bytes(op_type)
                    if frame.kind == MessageKind::Node
                        && field_number == 4
                        && op_type == b"EPContext" =>
                {
                    return Err(EmbeddedOnnxModelError::EpContextNode);
                }
                FieldValue::Bytes(bytes) => {
                    if frame.kind == MessageKind::Model && field_number == 7 {
                        has_graph = true;
                    }
                    if let Some(kind) = nested_message_kind(frame.kind, field_number) {
                        child = Some(Frame {
                            bytes,
                            offset: 0,
                            kind,
                        });
                    }
                }
                FieldValue::Varint(_) | FieldValue::Other => {}
            }
        }

        if let Some(child) = child {
            push_frame(&mut frames, child)?;
        }
    }

    if !has_ir_version {
        return Err(EmbeddedOnnxModelError::MissingIrVersion);
    }
    if !has_graph {
        return Err(EmbeddedOnnxModelError::MissingGraph);
    }
    Ok(())
}

const MAX_FIELD_NUMBER: u64 = (1_u64 << 29) - 1;

fn expected_wire_type(kind: MessageKind, field_number: u64) -> Option<u8> {
    match (kind, field_number) {
        (MessageKind::Model, 1) | (MessageKind::Tensor, 14) => Some(0),
        (MessageKind::Model, 7 | 20 | 25)
        | (MessageKind::TrainingInfo | MessageKind::SparseTensor, 1 | 2)
        | (MessageKind::Graph, 1 | 5 | 15)
        | (MessageKind::Node, 4 | 5)
        | (MessageKind::Attribute, 5 | 6 | 10 | 11 | 22 | 23)
        | (MessageKind::Function, 7 | 11) => Some(2),
        _ => None,
    }
}

fn nested_message_kind(kind: MessageKind, field_number: u64) -> Option<MessageKind> {
    match (kind, field_number) {
        (MessageKind::Model, 7)
        | (MessageKind::TrainingInfo, 1 | 2)
        | (MessageKind::Attribute, 6 | 11) => Some(MessageKind::Graph),
        (MessageKind::Model, 20) => Some(MessageKind::TrainingInfo),
        (MessageKind::Model, 25) => Some(MessageKind::Function),
        (MessageKind::Graph, 1) | (MessageKind::Function, 7) => Some(MessageKind::Node),
        (MessageKind::Graph, 5)
        | (MessageKind::Attribute, 5 | 10)
        | (MessageKind::SparseTensor, 1 | 2) => Some(MessageKind::Tensor),
        (MessageKind::Graph, 15) | (MessageKind::Attribute, 22 | 23) => {
            Some(MessageKind::SparseTensor)
        }
        (MessageKind::Node, 5) | (MessageKind::Function, 11) => Some(MessageKind::Attribute),
        _ => None,
    }
}

fn push_frame<'a>(
    frames: &mut Vec<Frame<'a>>,
    frame: Frame<'a>,
) -> Result<(), EmbeddedOnnxModelError> {
    frames
        .try_reserve(1)
        .map_err(|_| EmbeddedOnnxModelError::ResourceExhausted)?;
    frames.push(frame);
    Ok(())
}

pub(crate) fn read_varint(bytes: &[u8], offset: &mut usize) -> Result<u64, EmbeddedOnnxModelError> {
    let mut value = 0_u64;
    for index in 0..10 {
        let byte = *bytes
            .get(*offset)
            .ok_or(EmbeddedOnnxModelError::InvalidProtobuf)?;
        *offset = offset
            .checked_add(1)
            .ok_or(EmbeddedOnnxModelError::InvalidProtobuf)?;

        if index == 9 {
            if byte & 0xfe != 0 {
                return Err(EmbeddedOnnxModelError::InvalidProtobuf);
            }
            value |= u64::from(byte) << 63;
            return Ok(value);
        }

        value |= u64::from(byte & 0x7f) << (index * 7);
        if byte & 0x80 == 0 {
            return Ok(value);
        }
    }
    Err(EmbeddedOnnxModelError::InvalidProtobuf)
}

pub(crate) fn read_field_value<'a>(
    bytes: &'a [u8],
    offset: &mut usize,
    wire_type: u8,
) -> Result<FieldValue<'a>, EmbeddedOnnxModelError> {
    match wire_type {
        0 => Ok(FieldValue::Varint(read_varint(bytes, offset)?)),
        1 => {
            take(bytes, offset, 8)?;
            Ok(FieldValue::Other)
        }
        2 => {
            let encoded_length = read_varint(bytes, offset)?;
            let length = usize::try_from(encoded_length)
                .map_err(|_| EmbeddedOnnxModelError::InvalidProtobuf)?;
            Ok(FieldValue::Bytes(take(bytes, offset, length)?))
        }
        5 => {
            take(bytes, offset, 4)?;
            Ok(FieldValue::Other)
        }
        _ => Err(EmbeddedOnnxModelError::InvalidProtobuf),
    }
}

pub(crate) fn take<'a>(
    bytes: &'a [u8],
    offset: &mut usize,
    length: usize,
) -> Result<&'a [u8], EmbeddedOnnxModelError> {
    let end = (*offset)
        .checked_add(length)
        .ok_or(EmbeddedOnnxModelError::InvalidProtobuf)?;
    let value = bytes
        .get(*offset..end)
        .ok_or(EmbeddedOnnxModelError::InvalidProtobuf)?;
    *offset = end;
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::{EmbeddedOnnxModelError as Error, validate_embedded_onnx_model};

    fn put_varint(mut value: usize, bytes: &mut Vec<u8>) {
        while value >= 0x80 {
            bytes.push((value.to_le_bytes()[0] & 0x7f) | 0x80);
            value >>= 7;
        }
        bytes.push(value.to_le_bytes()[0]);
    }

    fn put_varint_field(bytes: &mut Vec<u8>, field_number: u8, value: usize) {
        put_varint(usize::from(field_number) << 3, bytes);
        put_varint(value, bytes);
    }

    fn put_bytes_field(bytes: &mut Vec<u8>, field_number: u8, value: &[u8]) {
        put_varint((usize::from(field_number) << 3) | 2, bytes);
        put_varint(value.len(), bytes);
        bytes.extend_from_slice(value);
    }

    fn varint_field(field_number: u8, value: usize) -> Vec<u8> {
        let mut bytes = Vec::new();
        put_varint_field(&mut bytes, field_number, value);
        bytes
    }

    fn bytes_field(field_number: u8, value: &[u8]) -> Vec<u8> {
        let mut bytes = Vec::new();
        put_bytes_field(&mut bytes, field_number, value);
        bytes
    }

    fn model(graph: &[u8]) -> Vec<u8> {
        let mut bytes = Vec::new();
        put_varint_field(&mut bytes, 1, 13);
        put_bytes_field(&mut bytes, 7, graph);
        bytes
    }

    fn external_tensor() -> Vec<u8> {
        bytes_field(13, &[])
    }

    fn graph_with_initializer(tensor: &[u8]) -> Vec<u8> {
        bytes_field(5, tensor)
    }

    fn graph_with_node(node: &[u8]) -> Vec<u8> {
        bytes_field(1, node)
    }

    fn node_with_attribute(attribute: &[u8]) -> Vec<u8> {
        bytes_field(5, attribute)
    }

    fn attribute_with_tensor_field(field_number: u8, tensor: &[u8]) -> Vec<u8> {
        bytes_field(field_number, tensor)
    }

    fn sparse_with_tensor(field_number: u8, tensor: &[u8]) -> Vec<u8> {
        bytes_field(field_number, tensor)
    }

    fn model_with_training_graph(field_number: u8, graph: &[u8]) -> Vec<u8> {
        let training = bytes_field(field_number, graph);
        let mut bytes = Vec::new();
        put_varint_field(&mut bytes, 1, 13);
        put_bytes_field(&mut bytes, 20, &training);
        bytes
    }

    fn model_with_function(function: &[u8]) -> Vec<u8> {
        let mut bytes = Vec::new();
        put_varint_field(&mut bytes, 1, 13);
        put_bytes_field(&mut bytes, 7, &[]);
        put_bytes_field(&mut bytes, 25, function);
        bytes
    }

    #[test]
    fn accepts_embedded_model_and_skips_misleading_raw_tensor_bytes() {
        let misleading_raw_data = [
            0x6a, 0x00, // Tensor.external_data field bytes.
            0x70, 0x01, // Tensor.data_location field bytes.
            0x22, 0x09, b'E', b'P', b'C', b'o', b'n', b't', b'e', b'x', b't', b'O', b'R', b'T',
            b'M',
        ];
        let tensor = bytes_field(9, &misleading_raw_data);
        let graph = graph_with_initializer(&tensor);

        assert_eq!(validate_embedded_onnx_model(&model(&graph)), Ok(()));
    }

    #[test]
    fn requires_ir_version_and_graph_and_rejects_versions_outside_the_pin() {
        assert_eq!(
            validate_embedded_onnx_model(&[]),
            Err(Error::MissingIrVersion)
        );

        let ir_only = varint_field(1, 13);
        assert_eq!(
            validate_embedded_onnx_model(&ir_only),
            Err(Error::MissingGraph)
        );

        for version in [0, 14] {
            let mut bytes = Vec::new();
            put_varint_field(&mut bytes, 1, version);
            put_bytes_field(&mut bytes, 7, &[]);
            assert_eq!(
                validate_embedded_onnx_model(&bytes),
                Err(Error::UnsupportedIrVersion)
            );
        }
    }

    #[test]
    fn rejects_ort_flatbuffer_identifier_at_the_file_identifier_offset() {
        assert_eq!(
            validate_embedded_onnx_model(b"xxxxORTM"),
            Err(Error::OrtFlatbufferNotSupported)
        );
    }

    #[test]
    fn rejects_external_data_at_every_reviewed_tensor_placement() {
        let tensor = external_tensor();
        let sparse_values = sparse_with_tensor(1, &tensor);
        let sparse_indices = sparse_with_tensor(2, &tensor);
        let attr_tensor = attribute_with_tensor_field(5, &tensor);
        let attr_tensors = attribute_with_tensor_field(10, &tensor);
        let graph_tensor = graph_with_initializer(&tensor);
        let attr_graph = attribute_with_tensor_field(6, &graph_tensor);
        let attr_graphs = attribute_with_tensor_field(11, &graph_tensor);
        let attr_sparse_values = attribute_with_tensor_field(22, &sparse_values);
        let attr_sparse_indices = attribute_with_tensor_field(22, &sparse_indices);
        let attr_sparse_tensors = attribute_with_tensor_field(23, &sparse_values);

        let mut graph_with_sparse_initializer = Vec::new();
        put_bytes_field(&mut graph_with_sparse_initializer, 15, &sparse_values);
        let mut graph_with_sparse_indices = Vec::new();
        put_bytes_field(&mut graph_with_sparse_indices, 15, &sparse_indices);

        let fixtures = [
            model(&graph_tensor),
            model(&graph_with_sparse_initializer),
            model(&graph_with_sparse_indices),
            model(&graph_with_node(&node_with_attribute(&attr_tensor))),
            model(&graph_with_node(&node_with_attribute(&attr_tensors))),
            model(&graph_with_node(&node_with_attribute(&attr_graph))),
            model(&graph_with_node(&node_with_attribute(&attr_graphs))),
            model(&graph_with_node(&node_with_attribute(&attr_sparse_values))),
            model(&graph_with_node(&node_with_attribute(&attr_sparse_indices))),
            model(&graph_with_node(&node_with_attribute(&attr_sparse_tensors))),
            model_with_training_graph(1, &graph_tensor),
            model_with_training_graph(2, &graph_tensor),
            model_with_function(&bytes_field(7, &node_with_attribute(&attr_tensor))),
            model_with_function(&bytes_field(11, &attr_tensor)),
        ];

        for fixture in fixtures {
            assert_eq!(
                validate_embedded_onnx_model(&fixture),
                Err(Error::ExternalTensorData)
            );
        }
    }

    #[test]
    fn rejects_non_default_data_location_even_when_a_later_duplicate_is_default() {
        let mut tensor = Vec::new();
        put_varint_field(&mut tensor, 14, 1);
        put_varint_field(&mut tensor, 14, 0);
        let graph = graph_with_initializer(&tensor);

        assert_eq!(
            validate_embedded_onnx_model(&model(&graph)),
            Err(Error::ExternalTensorLocation)
        );
    }

    #[test]
    fn rejects_epcontext_in_function_and_training_paths_regardless_of_domain() {
        let mut node = Vec::new();
        put_bytes_field(&mut node, 4, b"EPContext");
        put_bytes_field(&mut node, 7, b"com.microsoft");
        let function = bytes_field(7, &node);
        let function_model = model_with_function(&function);

        let training_graph = graph_with_node(&node);
        let training_model = model_with_training_graph(2, &training_graph);

        assert_eq!(
            validate_embedded_onnx_model(&function_model),
            Err(Error::EpContextNode)
        );
        assert_eq!(
            validate_embedded_onnx_model(&training_model),
            Err(Error::EpContextNode)
        );
    }

    #[test]
    fn scans_every_duplicate_and_ignores_attribute_discriminator() {
        let tensor = external_tensor();
        let mut attribute = Vec::new();
        put_varint_field(&mut attribute, 20, 2); // Declares INT, but field 5 still contains a tensor.
        put_bytes_field(&mut attribute, 5, &[]);
        put_bytes_field(&mut attribute, 5, &tensor);

        let mut graph = Vec::new();
        put_bytes_field(&mut graph, 1, &node_with_attribute(&attribute));
        let mut bytes = model(&graph);
        // A duplicate model graph must also be inspected, even though protobuf
        // singular-message merge behavior can obscure occurrence boundaries.
        let duplicate_graph = graph_with_initializer(&tensor);
        put_bytes_field(&mut bytes, 7, &duplicate_graph);

        assert_eq!(
            validate_embedded_onnx_model(&bytes),
            Err(Error::ExternalTensorData)
        );

        let mut duplicate_graphs = model(&[]);
        let graph_with_external_tensor = graph_with_initializer(&tensor);
        put_bytes_field(&mut duplicate_graphs, 7, &graph_with_external_tensor);
        assert_eq!(
            validate_embedded_onnx_model(&duplicate_graphs),
            Err(Error::ExternalTensorData)
        );

        let mut duplicate_external_fields = Vec::new();
        put_bytes_field(&mut duplicate_external_fields, 13, &[]);
        put_bytes_field(&mut duplicate_external_fields, 13, b"location");
        let graph = graph_with_initializer(&duplicate_external_fields);
        assert_eq!(
            validate_embedded_onnx_model(&model(&graph)),
            Err(Error::ExternalTensorData)
        );
    }

    #[test]
    fn rejects_epcontext_hidden_by_a_later_duplicate_op_type() {
        let mut node = Vec::new();
        put_bytes_field(&mut node, 4, b"EPContext");
        put_bytes_field(&mut node, 4, b"Relu");
        let graph = graph_with_node(&node);

        assert_eq!(
            validate_embedded_onnx_model(&model(&graph)),
            Err(Error::EpContextNode)
        );
    }

    #[test]
    fn rejects_inspected_fields_with_wrong_wire_types() {
        let wrong_ir_wire = bytes_field(1, &[]);
        assert_eq!(
            validate_embedded_onnx_model(&wrong_ir_wire),
            Err(Error::InvalidProtobuf)
        );

        let mut wrong_graph_wire = Vec::new();
        put_varint_field(&mut wrong_graph_wire, 1, 13);
        put_varint_field(&mut wrong_graph_wire, 7, 0);
        assert_eq!(
            validate_embedded_onnx_model(&wrong_graph_wire),
            Err(Error::InvalidProtobuf)
        );

        let wrong_data_location_wire = bytes_field(14, &[]);
        let tensor = graph_with_initializer(&wrong_data_location_wire);
        assert_eq!(
            validate_embedded_onnx_model(&model(&tensor)),
            Err(Error::InvalidProtobuf)
        );

        let wrong_op_type_wire = varint_field(4, 1);
        let graph = graph_with_node(&wrong_op_type_wire);
        assert_eq!(
            validate_embedded_onnx_model(&model(&graph)),
            Err(Error::InvalidProtobuf)
        );

        let mut external_data_wrong_wire = Vec::new();
        put_varint_field(&mut external_data_wrong_wire, 13, 0);
        let graph = graph_with_initializer(&external_data_wrong_wire);
        assert_eq!(
            validate_embedded_onnx_model(&model(&graph)),
            Err(Error::ExternalTensorData)
        );
    }

    #[test]
    fn rejects_malformed_tags_lengths_varints_and_fixed_width_values() {
        let malformed = [
            vec![0x80],             // Truncated tag varint.
            vec![0x00],             // Zero field tag.
            vec![0x0b],             // Start group.
            vec![0x0c],             // End group.
            vec![0x0e],             // Invalid wire type 6.
            vec![0x0f],             // Invalid wire type 7.
            vec![0x09, 0x01],       // Truncated fixed64.
            vec![0x0d, 0x01, 0x02], // Truncated fixed32.
            vec![0x12, 0x02, 0x01], // Truncated length-delimited value.
            vec![
                0x08, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x02,
            ],
            vec![
                0x12, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x01,
            ],
        ];

        for bytes in malformed {
            assert_eq!(
                validate_embedded_onnx_model(&bytes),
                Err(Error::InvalidProtobuf)
            );
        }
    }

    #[test]
    fn traverses_deeply_nested_graphs_without_recursive_calls_or_depth_limit() {
        let mut graph = Vec::new();
        for _ in 0..8_192 {
            let attribute = bytes_field(6, &graph);
            let node = node_with_attribute(&attribute);
            graph = graph_with_node(&node);
        }

        assert_eq!(validate_embedded_onnx_model(&model(&graph)), Ok(()));
    }

    #[test]
    fn displays_only_stable_sanitized_codes() {
        assert_eq!(
            Error::ExternalTensorData.to_string(),
            "EMBEDDED_ONNX_EXTERNAL_TENSOR_DATA"
        );
        assert_eq!(
            Error::ExternalTensorData.code(),
            "EMBEDDED_ONNX_EXTERNAL_TENSOR_DATA"
        );
    }
}
