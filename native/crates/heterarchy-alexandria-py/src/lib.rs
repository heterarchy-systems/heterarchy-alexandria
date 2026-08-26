//! `PyO3` conversion adapter for heterarchy-alexandria native compute.
//!
//! This crate must remain a narrow Python/Rust boundary and must not own domain compute.

mod bulk_embedding_runtime_wire;
mod bulk_embedding_wire;
mod context_reindex_manifest_wire;
mod document_index_wire;
pub mod embedding_runtime_registry;
mod fastembed_runtime;
mod graph_traversal_wire;
mod raw_data_integrity_compact;
mod raw_data_integrity_wire;
mod reconciliation_candidate_wire;
mod retrieval_kernel_compact;
mod retrieval_kernel_wire;

use bulk_embedding_runtime_wire::run_bulk_embedding_payload;
use bulk_embedding_wire::{finalize_bulk_embedding_payload, prepare_bulk_embedding_payload};
use context_reindex_manifest_wire::compute_context_reindex_manifest_payload;
use document_index_wire::compute_document_index_batch_payload;
use fastembed_runtime::infer_query_input;
use graph_traversal_wire::{
    compute_graph_candidate_selection_payload, compute_graph_traversal_payload,
};
use heterarchy_alexandria_core::ComputeContractVersion;
use heterarchy_alexandria_core::document_analysis::{
    DocumentBatch, DocumentId, DocumentInput, RelativeVaultPath, analyze_batch,
};
use heterarchy_alexandria_core::graph_compute::{
    GRAPH_COMPUTE_VERSION, GraphComputeRequest, GraphIndexStatus, GraphLineageRequest,
    GraphProjection, GraphProjectionEdge, GraphProjectionNode, GraphSourceEdge, GraphSourceNote,
    GraphTraversalRequest, TraversalDirection, compute_graph,
};
use heterarchy_alexandria_core::hash_fingerprint::{
    CurrentComputeSnapshot, EmbeddingFingerprintInput, HASH_FINGERPRINT_VERSION, HashBatch,
    HashDocumentInput, PreviousComputeSnapshot, compute_hash_batch,
};
use heterarchy_alexandria_core::markdown_chunking::{
    ChunkBatch, ChunkDocumentInput, ChunkPolicy, MARKDOWN_CHUNKING_VERSION, chunk_batch,
};
use heterarchy_alexandria_core::reference_extraction::{
    FrontmatterEdgeInput, REFERENCE_EXTRACTION_VERSION, ReferenceBatch, ReferenceDocumentInput,
    extract_reference_batch,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use raw_data_integrity_wire::scan_raw_data_integrity_payload;
use reconciliation_candidate_wire::compute_reconciliation_candidates_payload;
use retrieval_kernel_compact::{
    retrieval_hybrid_candidate_limit, retrieval_merge_hybrid_indices,
    retrieval_merge_hybrid_indices_with_trace, retrieval_rank_best_indices,
};
use retrieval_kernel_wire::compute_retrieval_kernel_payload;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DocumentBatchWire {
    contract_version: u16,
    documents: Vec<DocumentWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DocumentWire {
    document_id: String,
    relative_path: String,
    text: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ChunkBatchWire {
    contract_version: u16,
    chunking_version: u16,
    max_chars: usize,
    overlap_chars: usize,
    documents: Vec<ChunkDocumentWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ChunkDocumentWire {
    document_id: String,
    relative_path: String,
    title: String,
    content: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ReferenceBatchWire {
    contract_version: u16,
    extraction_version: u16,
    documents: Vec<ReferenceDocumentWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ReferenceDocumentWire {
    note_id: String,
    relative_path: String,
    alexandria_root: String,
    body: String,
    frontmatter_edges: Vec<FrontmatterEdgeWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct FrontmatterEdgeWire {
    target_path: Option<String>,
    target_note_id: Option<String>,
    relation: String,
    source_field: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct HashBatchWire {
    contract_version: u16,
    hashing_version: u16,
    documents: Vec<HashDocumentWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct HashDocumentWire {
    document_id: String,
    relative_path: String,
    text: String,
    embedding_fingerprint: Option<EmbeddingFingerprintWire>,
    indexed_at: Option<String>,
    previous: PreviousComputeWire,
    current_chunk_identities: Option<Vec<String>>,
    current_edge_identities: Option<Vec<String>>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct EmbeddingFingerprintWire {
    provider: String,
    model: String,
    provider_version: String,
    pooling_mode: String,
    normalize: bool,
    dimensions: i64,
    document_input_format: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PreviousComputeWire {
    content_hash: Option<String>,
    embedding_fingerprint_key: Option<String>,
    chunk_identities: Option<Vec<String>>,
    edge_identities: Option<Vec<String>>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphComputeWire {
    contract_version: u16,
    graph_compute_version: u16,
    batch_size: usize,
    source_notes: Vec<GraphSourceNoteWire>,
    source_edges: Vec<GraphSourceEdgeWire>,
    previous_projection: Option<GraphProjectionWire>,
    traversal_requests: Vec<GraphTraversalRequestWire>,
    lineage_requests: Vec<GraphLineageRequestWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphSourceNoteWire {
    note_id: String,
    relative_path: String,
    alexandria_type: String,
    title: String,
    status: String,
    project: Option<String>,
    aliases: Vec<String>,
    index_status: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphSourceEdgeWire {
    edge_id: String,
    source_note_id: String,
    source_path: String,
    target_note_id: Option<String>,
    target_path: String,
    relation: String,
    confidence: f64,
    source_kind: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphProjectionWire {
    nodes: Vec<GraphProjectionNodeWire>,
    edges: Vec<GraphProjectionEdgeWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphProjectionNodeWire {
    note_id: String,
    relative_path: String,
    alexandria_type: String,
    title: String,
    status: String,
    project: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphProjectionEdgeWire {
    edge_id: String,
    source_note_id: String,
    source_path: String,
    target_note_id: String,
    target_path: String,
    relation: String,
    confidence: f64,
    source_kind: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphTraversalRequestWire {
    request_id: String,
    start_note_id: String,
    direction: String,
    relations: Vec<String>,
    max_depth: usize,
    max_results: usize,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphLineageRequestWire {
    request_id: String,
    note_id: String,
    max_depth: usize,
    max_results: usize,
}

#[pyfunction]
fn compute_contract_version() -> u16 {
    ComputeContractVersion::CURRENT.value()
}

#[pyfunction]
fn native_package_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pyfunction]
fn native_git_revision() -> &'static str {
    env!("HETERARCHY_ALEXANDRIA_NATIVE_GIT_REVISION")
}

#[pyfunction]
fn native_build_profile() -> &'static str {
    env!("HETERARCHY_ALEXANDRIA_NATIVE_BUILD_PROFILE")
}

#[pyfunction]
fn feature_authority_schema_version() -> u16 {
    1
}

#[pyfunction]
fn analyze_document_batch_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || analyze_document_batch_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn compute_document_index_batch_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || compute_document_index_batch_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn scan_raw_data_integrity_batch_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || scan_raw_data_integrity_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn chunk_markdown_batch_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || chunk_markdown_batch_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn extract_reference_batch_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || extract_reference_batch_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn compute_hash_batch_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || compute_hash_batch_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn compute_graph_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || compute_graph_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn traverse_graph_projection_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || compute_graph_traversal_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn select_graph_projection_candidates_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || compute_graph_candidate_selection_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn prepare_bulk_embedding_batch_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || prepare_bulk_embedding_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn finalize_bulk_embedding_batch_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || finalize_bulk_embedding_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn run_bulk_embedding_batch_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || run_bulk_embedding_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn embed_multilingual_e5_query(
    python: Python<'_>,
    query_input: String,
    cache_directory: Option<String>,
    threads: usize,
) -> PyResult<Vec<f32>> {
    python
        .detach(move || infer_query_input(&query_input, cache_directory.as_deref(), threads))
        .map_err(PyValueError::new_err)
}

#[pyfunction]
fn compute_retrieval_kernel_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || compute_retrieval_kernel_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn compute_context_reindex_manifest_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || compute_context_reindex_manifest_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

#[pyfunction]
fn compute_reconciliation_candidates_json<'python>(
    python: Python<'python>,
    payload: &[u8],
) -> PyResult<Bound<'python, PyBytes>> {
    let owned_payload = payload.to_vec();
    let encoded = python
        .detach(move || compute_reconciliation_candidates_payload(&owned_payload))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(python, &encoded))
}

fn analyze_document_batch_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: DocumentBatchWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_DOCUMENT_ANALYSIS_INPUT_ERROR: {error}"))?;
    validate_contract_version(
        wire.contract_version,
        "NATIVE_DOCUMENT_ANALYSIS_CONTRACT_ERROR",
    )?;

    let documents = wire
        .documents
        .into_iter()
        .map(document_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let batch = DocumentBatch::new(documents)
        .map_err(|error| format!("NATIVE_DOCUMENT_ANALYSIS_INPUT_ERROR: {error}"))?;
    let result = analyze_batch(batch);
    serde_json::to_vec(&result)
        .map_err(|error| format!("NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: {error}"))
}

fn chunk_markdown_batch_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: ChunkBatchWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_MARKDOWN_CHUNKING_INPUT_ERROR: {error}"))?;
    validate_contract_version(
        wire.contract_version,
        "NATIVE_MARKDOWN_CHUNKING_CONTRACT_ERROR",
    )?;
    if wire.chunking_version != MARKDOWN_CHUNKING_VERSION {
        return Err(format!(
            "NATIVE_MARKDOWN_CHUNKING_CONTRACT_ERROR: expected chunking version {MARKDOWN_CHUNKING_VERSION}, found {}",
            wire.chunking_version
        ));
    }
    let policy = ChunkPolicy::new(wire.max_chars, wire.overlap_chars)
        .map_err(|error| format!("NATIVE_MARKDOWN_CHUNKING_INPUT_ERROR: {error}"))?;
    let documents = wire
        .documents
        .into_iter()
        .map(chunk_document_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let batch = ChunkBatch::new(policy, documents)
        .map_err(|error| format!("NATIVE_MARKDOWN_CHUNKING_INPUT_ERROR: {error}"))?;
    let result = chunk_batch(batch)
        .map_err(|error| format!("NATIVE_MARKDOWN_CHUNKING_INVARIANT_ERROR: {error}"))?;
    serde_json::to_vec(&result)
        .map_err(|error| format!("NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR: {error}"))
}

fn extract_reference_batch_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: ReferenceBatchWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_REFERENCE_EXTRACTION_INPUT_ERROR: {error}"))?;
    validate_contract_version(
        wire.contract_version,
        "NATIVE_REFERENCE_EXTRACTION_CONTRACT_ERROR",
    )?;
    if wire.extraction_version != REFERENCE_EXTRACTION_VERSION {
        return Err(format!(
            "NATIVE_REFERENCE_EXTRACTION_CONTRACT_ERROR: expected extraction version {REFERENCE_EXTRACTION_VERSION}, found {}",
            wire.extraction_version
        ));
    }
    let documents = wire
        .documents
        .into_iter()
        .map(reference_document_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let batch = ReferenceBatch::new(documents)
        .map_err(|error| format!("NATIVE_REFERENCE_EXTRACTION_INPUT_ERROR: {error}"))?;
    let result = extract_reference_batch(batch)
        .map_err(|error| format!("NATIVE_REFERENCE_EXTRACTION_INVARIANT_ERROR: {error}"))?;
    serde_json::to_vec(&result)
        .map_err(|error| format!("NATIVE_REFERENCE_EXTRACTION_OUTPUT_ERROR: {error}"))
}

fn compute_hash_batch_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: HashBatchWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_HASH_FINGERPRINT_INPUT_ERROR: {error}"))?;
    validate_contract_version(
        wire.contract_version,
        "NATIVE_HASH_FINGERPRINT_CONTRACT_ERROR",
    )?;
    if wire.hashing_version != HASH_FINGERPRINT_VERSION {
        return Err(format!(
            "NATIVE_HASH_FINGERPRINT_CONTRACT_ERROR: expected hashing version {HASH_FINGERPRINT_VERSION}, found {}",
            wire.hashing_version
        ));
    }
    let documents = wire
        .documents
        .into_iter()
        .map(hash_document_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let batch = HashBatch::new(documents)
        .map_err(|error| format!("NATIVE_HASH_FINGERPRINT_INPUT_ERROR: {error}"))?;
    let result = compute_hash_batch(batch)
        .map_err(|error| format!("NATIVE_HASH_FINGERPRINT_INVARIANT_ERROR: {error}"))?;
    serde_json::to_vec(&result)
        .map_err(|error| format!("NATIVE_HASH_FINGERPRINT_OUTPUT_ERROR: {error}"))
}

fn compute_graph_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: GraphComputeWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_GRAPH_COMPUTE_INPUT_ERROR: {error}"))?;
    validate_contract_version(wire.contract_version, "NATIVE_GRAPH_COMPUTE_CONTRACT_ERROR")?;
    if wire.graph_compute_version != GRAPH_COMPUTE_VERSION {
        return Err(format!(
            "NATIVE_GRAPH_COMPUTE_CONTRACT_ERROR: expected graph compute version {GRAPH_COMPUTE_VERSION}, found {}",
            wire.graph_compute_version
        ));
    }
    let source_notes = wire
        .source_notes
        .into_iter()
        .map(graph_source_note_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let source_edges = wire
        .source_edges
        .into_iter()
        .map(graph_source_edge_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let previous_projection = wire.previous_projection.map(graph_projection_from_wire);
    let traversals = wire
        .traversal_requests
        .into_iter()
        .map(graph_traversal_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let lineages = wire
        .lineage_requests
        .into_iter()
        .map(|request| GraphLineageRequest {
            request_id: request.request_id,
            note_id: request.note_id,
            max_depth: request.max_depth,
            max_results: request.max_results,
        })
        .collect();
    let request = GraphComputeRequest::new(
        source_notes,
        source_edges,
        previous_projection,
        wire.batch_size,
        traversals,
        lineages,
    )
    .map_err(|error| format!("NATIVE_GRAPH_COMPUTE_INPUT_ERROR: {error}"))?;
    let result = compute_graph(request)
        .map_err(|error| format!("NATIVE_GRAPH_COMPUTE_INVARIANT_ERROR: {error}"))?;
    serde_json::to_vec(&result)
        .map_err(|error| format!("NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: {error}"))
}

pub(crate) fn validate_contract_version(actual: u16, error_code: &str) -> Result<(), String> {
    let expected = ComputeContractVersion::CURRENT.value();
    if actual != expected {
        return Err(format!(
            "{error_code}: expected contract version {expected}, found {actual}"
        ));
    }
    Ok(())
}

fn document_from_wire(wire: DocumentWire) -> Result<DocumentInput, String> {
    let document_id = document_id(wire.document_id, "NATIVE_DOCUMENT_ANALYSIS_INPUT_ERROR")?;
    let relative_path = relative_path(wire.relative_path, "NATIVE_DOCUMENT_ANALYSIS_INPUT_ERROR")?;
    DocumentInput::new(document_id, relative_path, wire.text)
        .map_err(|error| format!("NATIVE_DOCUMENT_ANALYSIS_INPUT_ERROR: {error}"))
}

fn chunk_document_from_wire(wire: ChunkDocumentWire) -> Result<ChunkDocumentInput, String> {
    let document_id = document_id(wire.document_id, "NATIVE_MARKDOWN_CHUNKING_INPUT_ERROR")?;
    let relative_path = relative_path(wire.relative_path, "NATIVE_MARKDOWN_CHUNKING_INPUT_ERROR")?;
    ChunkDocumentInput::new(document_id, relative_path, wire.title, wire.content)
        .map_err(|error| format!("NATIVE_MARKDOWN_CHUNKING_INPUT_ERROR: {error}"))
}

fn reference_document_from_wire(
    wire: ReferenceDocumentWire,
) -> Result<ReferenceDocumentInput, String> {
    let note_id = document_id(wire.note_id, "NATIVE_REFERENCE_EXTRACTION_INPUT_ERROR")?;
    let relative_path = relative_path(
        wire.relative_path,
        "NATIVE_REFERENCE_EXTRACTION_INPUT_ERROR",
    )?;
    let frontmatter_edges = wire
        .frontmatter_edges
        .into_iter()
        .map(frontmatter_edge_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    ReferenceDocumentInput::new(
        note_id,
        relative_path,
        wire.alexandria_root,
        wire.body,
        frontmatter_edges,
    )
    .map_err(|error| format!("NATIVE_REFERENCE_EXTRACTION_INPUT_ERROR: {error}"))
}

fn frontmatter_edge_from_wire(wire: FrontmatterEdgeWire) -> Result<FrontmatterEdgeInput, String> {
    FrontmatterEdgeInput::new(
        wire.target_path,
        wire.target_note_id,
        wire.relation,
        wire.source_field,
    )
    .map_err(|error| format!("NATIVE_REFERENCE_EXTRACTION_INPUT_ERROR: {error}"))
}

fn hash_document_from_wire(wire: HashDocumentWire) -> Result<HashDocumentInput, String> {
    let document_id = document_id(wire.document_id, "NATIVE_HASH_FINGERPRINT_INPUT_ERROR")?;
    let relative_path = relative_path(wire.relative_path, "NATIVE_HASH_FINGERPRINT_INPUT_ERROR")?;
    let current = CurrentComputeSnapshot {
        embedding_fingerprint: wire
            .embedding_fingerprint
            .map(embedding_fingerprint_from_wire),
        indexed_at: wire.indexed_at,
        chunk_identities: wire.current_chunk_identities,
        edge_identities: wire.current_edge_identities,
    };
    let previous = PreviousComputeSnapshot {
        content_hash: wire.previous.content_hash,
        embedding_fingerprint_key: wire.previous.embedding_fingerprint_key,
        chunk_identities: wire.previous.chunk_identities,
        edge_identities: wire.previous.edge_identities,
    };
    HashDocumentInput::new(document_id, relative_path, wire.text, current, previous)
        .map_err(|error| format!("NATIVE_HASH_FINGERPRINT_INPUT_ERROR: {error}"))
}

fn embedding_fingerprint_from_wire(wire: EmbeddingFingerprintWire) -> EmbeddingFingerprintInput {
    EmbeddingFingerprintInput::new(
        wire.provider,
        wire.model,
        wire.provider_version,
        wire.pooling_mode,
        wire.normalize,
        wire.dimensions,
        wire.document_input_format,
    )
}

fn graph_source_note_from_wire(wire: GraphSourceNoteWire) -> Result<GraphSourceNote, String> {
    let note_id = document_id(wire.note_id, "NATIVE_GRAPH_COMPUTE_INPUT_ERROR")?;
    let relative_path = relative_path(wire.relative_path, "NATIVE_GRAPH_COMPUTE_INPUT_ERROR")?;
    Ok(GraphSourceNote {
        note_id,
        relative_path,
        alexandria_type: wire.alexandria_type,
        title: wire.title,
        status: wire.status,
        project: wire.project,
        aliases: wire.aliases,
        index_status: graph_index_status(&wire.index_status)?,
    })
}

fn graph_source_edge_from_wire(wire: GraphSourceEdgeWire) -> Result<GraphSourceEdge, String> {
    if !wire.confidence.is_finite() {
        return Err(format!(
            "NATIVE_GRAPH_COMPUTE_INPUT_ERROR: edge {} confidence must be finite",
            wire.edge_id
        ));
    }
    Ok(GraphSourceEdge {
        edge_id: wire.edge_id,
        source_note_id: wire.source_note_id,
        source_path: wire.source_path,
        target_note_id: wire.target_note_id,
        target_path: wire.target_path,
        relation: wire.relation,
        confidence: wire.confidence,
        source_kind: wire.source_kind,
    })
}

fn graph_projection_from_wire(wire: GraphProjectionWire) -> GraphProjection {
    GraphProjection {
        nodes: wire
            .nodes
            .into_iter()
            .map(|node| GraphProjectionNode {
                note_id: node.note_id,
                relative_path: node.relative_path,
                alexandria_type: node.alexandria_type,
                title: node.title,
                status: node.status,
                project: node.project,
            })
            .collect(),
        edges: wire
            .edges
            .into_iter()
            .map(|edge| GraphProjectionEdge {
                edge_id: edge.edge_id,
                source_note_id: edge.source_note_id,
                source_path: edge.source_path,
                target_note_id: edge.target_note_id,
                target_path: edge.target_path,
                relation: edge.relation,
                confidence: edge.confidence,
                source_kind: edge.source_kind,
            })
            .collect(),
    }
}

fn graph_traversal_from_wire(
    wire: GraphTraversalRequestWire,
) -> Result<GraphTraversalRequest, String> {
    Ok(GraphTraversalRequest {
        request_id: wire.request_id,
        start_note_id: wire.start_note_id,
        direction: graph_direction(&wire.direction)?,
        relations: wire.relations,
        max_depth: wire.max_depth,
        max_results: wire.max_results,
    })
}

fn graph_index_status(value: &str) -> Result<GraphIndexStatus, String> {
    match value {
        "indexed" => Ok(GraphIndexStatus::Indexed),
        "stale" => Ok(GraphIndexStatus::Stale),
        "error" => Ok(GraphIndexStatus::Error),
        other => Err(format!(
            "NATIVE_GRAPH_COMPUTE_INPUT_ERROR: unknown graph index status {other}"
        )),
    }
}

fn graph_direction(value: &str) -> Result<TraversalDirection, String> {
    match value {
        "outgoing" => Ok(TraversalDirection::Outgoing),
        "incoming" => Ok(TraversalDirection::Incoming),
        "both" => Ok(TraversalDirection::Both),
        other => Err(format!(
            "NATIVE_GRAPH_COMPUTE_INPUT_ERROR: unknown graph traversal direction {other}"
        )),
    }
}

fn document_id(value: String, error_code: &str) -> Result<DocumentId, String> {
    DocumentId::new(value).map_err(|error| format!("{error_code}: {error}"))
}

fn relative_path(value: String, error_code: &str) -> Result<RelativeVaultPath, String> {
    RelativeVaultPath::new(value).map_err(|error| format!("{error_code}: {error}"))
}

#[pymodule]
fn heterarchy_alexandria_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(pyo3::wrap_pyfunction!(compute_contract_version, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(native_package_version, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(native_git_revision, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(native_build_profile, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        feature_authority_schema_version,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(analyze_document_batch_json, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        scan_raw_data_integrity_batch_json,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        raw_data_integrity_compact::scan_raw_data_integrity_compact,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        compute_document_index_batch_json,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(chunk_markdown_batch_json, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        extract_reference_batch_json,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(compute_hash_batch_json, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(compute_graph_json, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        traverse_graph_projection_json,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        select_graph_projection_candidates_json,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        prepare_bulk_embedding_batch_json,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        finalize_bulk_embedding_batch_json,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        run_bulk_embedding_batch_json,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(embed_multilingual_e5_query, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        compute_retrieval_kernel_json,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        retrieval_hybrid_candidate_limit,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        retrieval_merge_hybrid_indices,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        retrieval_merge_hybrid_indices_with_trace,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(retrieval_rank_best_indices, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        compute_context_reindex_manifest_json,
        module
    )?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        compute_reconciliation_candidates_json,
        module
    )?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::{
        analyze_document_batch_payload, chunk_markdown_batch_payload, compute_contract_version,
        compute_graph_payload, compute_hash_batch_payload, extract_reference_batch_payload,
        feature_authority_schema_version, native_build_profile, native_git_revision,
        native_package_version,
    };

    #[test]
    fn adapter_exposes_core_contract_version() {
        assert_eq!(compute_contract_version(), 1);
    }

    #[test]
    fn adapter_exposes_runtime_provenance_contract() {
        assert!(!native_package_version().is_empty());
        assert!(!native_git_revision().is_empty());
        assert!(!native_build_profile().is_empty());
        assert_eq!(feature_authority_schema_version(), 1);
    }

    #[test]
    fn adapter_runs_one_coarse_document_batch() {
        let payload = br#"{
            "contract_version": 1,
            "documents": [
                {
                    "document_id": "case-1",
                    "relative_path": "Contexts/Case 1.md",
                    "text": "---\ntitle: Case 1\n---\n# Body\n"
                },
                {
                    "document_id": "case-2",
                    "relative_path": "Contexts/Case 2.md",
                    "text": "---\nid: one\nid: two\n---\n"
                }
            ]
        }"#;
        let encoded = match analyze_document_batch_payload(payload) {
            Ok(value) => value,
            Err(error) => unreachable!("valid adapter payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["contract_version"], 1);
        assert_eq!(decoded["analysis_version"], 1);
        assert_eq!(decoded["results"][0]["status"], "success");
        assert_eq!(decoded["results"][1]["status"], "error");
        assert_eq!(
            decoded["results"][1]["error"]["code"],
            "FRONTMATTER_PARSE_ERROR"
        );
    }

    #[test]
    fn adapter_runs_one_coarse_markdown_chunk_batch() {
        let payload = br##"{
            "contract_version": 1,
            "chunking_version": 1,
            "max_chars": 1400,
            "overlap_chars": 160,
            "documents": [
                {
                    "document_id": "case-1",
                    "relative_path": "Contexts/Case 1.md",
                    "title": "Case 1",
                    "content": "# Case 1\n\n## Summary\nBody\n"
                },
                {
                    "document_id": "case-2",
                    "relative_path": "Contexts/Case 2.md",
                    "title": "Fallback",
                    "content": ""
                }
            ]
        }"##;
        let encoded = match chunk_markdown_batch_payload(payload) {
            Ok(value) => value,
            Err(error) => unreachable!("valid chunk adapter payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("chunk adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["contract_version"], 1);
        assert_eq!(decoded["chunking_version"], 1);
        assert_eq!(
            decoded["results"][0]["chunks"].as_array().map(Vec::len),
            Some(2)
        );
        assert_eq!(decoded["results"][1]["chunks"][0]["content"], "Fallback");
    }

    #[test]
    fn adapter_runs_one_coarse_reference_extraction_batch() {
        let payload = br#"{
            "contract_version": 1,
            "extraction_version": 1,
            "documents": [
                {
                    "note_id": "current",
                    "relative_path": "Alexandria/Contexts/Current.md",
                    "alexandria_root": "Alexandria",
                    "body": "Read [[Contexts/Source#Evidence|source]] and ![[Assets/Diagram]].",
                    "frontmatter_edges": [
                        {
                            "target_path": "START_HERE.md",
                            "target_note_id": "start",
                            "relation": "cites",
                            "source_field": "source_refs"
                        }
                    ]
                }
            ]
        }"#;
        let encoded = match extract_reference_batch_payload(payload) {
            Ok(value) => value,
            Err(error) => unreachable!("valid reference adapter payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("reference adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["contract_version"], 1);
        assert_eq!(decoded["extraction_version"], 1);
        assert_eq!(
            decoded["results"][0]["references"].as_array().map(Vec::len),
            Some(2)
        );
        assert_eq!(
            decoded["results"][0]["edges"].as_array().map(Vec::len),
            Some(3)
        );
        assert_eq!(decoded["results"][0]["references"][1]["kind"], "embed");
    }

    #[test]
    fn adapter_runs_one_coarse_hash_fingerprint_batch() {
        let payload = br#"{
            "contract_version": 1,
            "hashing_version": 1,
            "documents": [
                {
                    "document_id": "case-1",
                    "relative_path": "Contexts/Case 1.md",
                    "text": "same",
                    "embedding_fingerprint": {
                        "provider": "fastembed",
                        "model": "intfloat/multilingual-e5-small",
                        "provider_version": "0.8.0",
                        "pooling_mode": "mean",
                        "normalize": true,
                        "dimensions": 384,
                        "document_input_format": "passage: {text}"
                    },
                    "indexed_at": "2026-08-22T03:30:00+09:00",
                    "previous": {
                        "content_hash": null,
                        "embedding_fingerprint_key": null,
                        "chunk_identities": ["b", "a"],
                        "edge_identities": ["edge-1"]
                    },
                    "current_chunk_identities": ["a", "b", "a"],
                    "current_edge_identities": ["edge-2"]
                }
            ]
        }"#;
        let encoded = match compute_hash_batch_payload(payload) {
            Ok(value) => value,
            Err(error) => unreachable!("valid hash adapter payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("hash adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["contract_version"], 1);
        assert_eq!(decoded["hashing_version"], 1);
        assert_eq!(
            decoded["results"][0]["content_hash"],
            "0967115f2813a3541eaef77de9d9d5773f1c0c04314b0bbfe4ff3b3b1c55b5d5"
        );
        assert_eq!(
            decoded["results"][0]["change_report"]["components"][2]["state"],
            "unchanged"
        );
        assert_eq!(
            decoded["results"][0]["change_report"]["components"][3]["state"],
            "changed"
        );
    }

    #[test]
    fn adapter_runs_one_coarse_graph_compute_request() {
        let payload = br#"{
            "contract_version": 1,
            "graph_compute_version": 1,
            "batch_size": 2,
            "source_notes": [
                {"note_id":"a","relative_path":"Contexts/a.md","alexandria_type":"context","title":"A","status":"active","project":null,"aliases":[],"index_status":"indexed"},
                {"note_id":"b","relative_path":"Contexts/b.md","alexandria_type":"context","title":"B","status":"active","project":null,"aliases":[],"index_status":"indexed"},
                {"note_id":"orphan","relative_path":"Contexts/orphan.md","alexandria_type":"context","title":"Orphan","status":"active","project":null,"aliases":[],"index_status":"indexed"}
            ],
            "source_edges": [
                {"edge_id":"e1","source_note_id":"a","source_path":"Contexts/a.md","target_note_id":"b","target_path":"Contexts/b.md","relation":"supersedes","confidence":1.0,"source_kind":"frontmatter"}
            ],
            "previous_projection": null,
            "traversal_requests": [
                {"request_id":"out-a","start_note_id":"a","direction":"outgoing","relations":[],"max_depth":3,"max_results":10}
            ],
            "lineage_requests": [
                {"request_id":"lineage-b","note_id":"b","max_depth":3,"max_results":10}
            ]
        }"#;
        let encoded = match compute_graph_payload(payload) {
            Ok(value) => value,
            Err(error) => unreachable!("valid graph adapter payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("graph adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["contract_version"], 1);
        assert_eq!(decoded["graph_compute_version"], 1);
        assert_eq!(
            decoded["projection"]["nodes"].as_array().map(Vec::len),
            Some(3)
        );
        assert_eq!(decoded["analysis"]["orphan_note_ids"][0], "orphan");
        assert_eq!(
            decoded["analysis"]["traversals"][0]["visits"]
                .as_array()
                .map(Vec::len),
            Some(2)
        );
        assert_eq!(
            decoded["analysis"]["lineages"][0]["superseded_by"][0]["note_id"],
            "a"
        );
    }

    #[test]
    fn adapter_rejects_unknown_contract_versions() {
        let payload = br#"{"contract_version": 2, "documents": []}"#;
        let result = analyze_document_batch_payload(payload);
        match result {
            Ok(_) => unreachable!("unsupported contract version must fail"),
            Err(error) => assert!(error.contains("expected contract version 1, found 2")),
        }
    }

    #[test]
    fn adapter_rejects_unknown_chunking_versions() {
        let payload = br#"{
            "contract_version": 1,
            "chunking_version": 2,
            "max_chars": 1400,
            "overlap_chars": 160,
            "documents": []
        }"#;
        let result = chunk_markdown_batch_payload(payload);
        match result {
            Ok(_) => unreachable!("unsupported chunking version must fail"),
            Err(error) => assert!(error.contains("expected chunking version 1, found 2")),
        }
    }

    #[test]
    fn adapter_rejects_unknown_reference_extraction_versions() {
        let payload = br#"{
            "contract_version": 1,
            "extraction_version": 2,
            "documents": []
        }"#;
        let result = extract_reference_batch_payload(payload);
        match result {
            Ok(_) => unreachable!("unsupported extraction version must fail"),
            Err(error) => assert!(error.contains("expected extraction version 1, found 2")),
        }
    }

    #[test]
    fn adapter_rejects_unknown_graph_compute_versions() {
        let payload = br#"{
            "contract_version": 1,
            "graph_compute_version": 2,
            "batch_size": 1,
            "source_notes": [],
            "source_edges": [],
            "previous_projection": null,
            "traversal_requests": [],
            "lineage_requests": []
        }"#;
        let result = compute_graph_payload(payload);
        match result {
            Ok(_) => unreachable!("unsupported graph compute version must fail"),
            Err(error) => assert!(error.contains("expected graph compute version 1, found 2")),
        }
    }

    #[test]
    fn adapter_rejects_unknown_hashing_versions() {
        let payload = br#"{
            "contract_version": 1,
            "hashing_version": 2,
            "documents": []
        }"#;
        let result = compute_hash_batch_payload(payload);
        match result {
            Ok(_) => unreachable!("unsupported hashing version must fail"),
            Err(error) => assert!(error.contains("expected hashing version 1, found 2")),
        }
    }
}
