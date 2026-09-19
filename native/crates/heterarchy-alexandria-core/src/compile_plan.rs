//! Deterministic knowledge compile planning over already-analyzed documents.
//!
//! This module is the single diff/invalidation authority for the knowledge
//! pipeline: it compares the current analyzed source snapshot against the
//! previous compiled state and emits a typed `CompilePlan` of document, chunk,
//! edge, and embedding work. It composes the existing chunking, reference
//! extraction, manifest validation, and hashing primitives; it never
//! re-implements them.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::context_reindex_manifest::{
    ContextReindexManifestCandidate, ContextReindexManifestResult,
    validate_context_reindex_manifest,
};
use crate::document_analysis::{DocumentId, RelativeVaultPath};
use crate::graph_compute::projection::{
    TargetResolution, candidate_link_names, canonical_path_key, indexed_notes_by_id,
    indexed_notes_by_path, notes_by_link_name, resolve_target_reference,
};
use crate::graph_compute::{GraphIndexStatus, GraphSourceNote};
use crate::hash_fingerprint::sha256_text;
use crate::markdown_chunking::{
    ChunkBatch, ChunkDocumentInput, ChunkDocumentOutcome, ChunkPolicy, ChunkRecord, chunk_batch,
};
use crate::reference_extraction::{
    EdgeCandidate, FrontmatterEdgeInput, ReferenceBatch, ReferenceDocumentInput,
    extract_reference_batch,
};

/// Version of the compile-plan contract and invalidation semantics.
pub const COMPILE_PLAN_VERSION: u16 = 1;

/// Deterministic compile policy supplied by the application boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompilePolicy {
    /// Maximum chunk content characters.
    pub chunk_max_chars: usize,
    /// Chunk overlap characters.
    pub chunk_overlap_chars: usize,
    /// Freshness key of the embedding model/policy the plan targets.
    pub embedding_fingerprint_key: String,
}

/// One analyzed current document submitted for planning.
#[derive(Debug, Clone, Deserialize)]
pub struct CompileDocumentInput {
    /// Vault-relative managed path.
    pub relative_path: String,
    /// Stable note identity from frontmatter.
    pub note_id: String,
    /// Note title.
    pub title: String,
    /// Alexandria note type tag.
    pub alexandria_type: String,
    /// Complete raw document text; ``None`` when the caller already supplies
    /// the authoritative source hash and chunk records.
    pub text: Option<String>,
    /// Authoritative raw-source hash supplied by the caller.
    pub source_hash: String,
    /// Body text produced by the analysis stage.
    pub body: String,
    /// Normalized frontmatter JSON.
    pub frontmatter: Value,
    /// Note lifecycle status used by graph authority filtering.
    pub status: String,
    /// Python-decoded aliases used by the graph link-name authority.
    pub aliases: Vec<String>,
    /// Python-policy frontmatter relation seeds.
    pub edge_seeds: Vec<CompileEdgeSeedInput>,
    /// Caller-provided chunk records (index + content hash) from an existing
    /// analysis pass; compile then skips re-chunking this document.
    pub provided_chunks: Option<Vec<CompileProvidedChunkInput>>,
    /// Caller-provided edge candidates from an existing extraction pass;
    /// compile then skips re-extraction and only resolves and diffs.
    pub provided_edges: Option<Vec<CompileProvidedEdgeInput>>,
    /// Manifest candidate for Context notes; ``None`` for other note types.
    pub manifest_candidate: Option<CompileManifestCandidateInput>,
}

/// One caller-provided chunk record for pass-through planning.
#[derive(Debug, Clone, Deserialize)]
pub struct CompileProvidedChunkInput {
    /// Stable chunk sequence.
    pub chunk_index: usize,
    /// Chunk content hash computed by the chunking authority.
    pub content_hash: String,
}

/// One caller-provided edge candidate for pass-through resolution and diffing.
#[derive(Debug, Clone, Deserialize)]
pub struct CompileProvidedEdgeInput {
    /// Canonical edge identifier.
    pub edge_id: String,
    /// Source note identity.
    pub source_note_id: String,
    /// Source note path.
    pub source_path: String,
    /// Known target note identity, when already resolved.
    pub target_note_id: Option<String>,
    /// Target path text.
    pub target_path: String,
    /// Relation name.
    pub relation: String,
    /// Compatibility confidence.
    pub confidence: f64,
    /// Source kind tag.
    pub source_kind: String,
}

/// Python-policy-resolved frontmatter relation candidate.
#[derive(Debug, Clone, Deserialize)]
pub struct CompileEdgeSeedInput {
    /// Target path selected by the relation policy.
    pub target_path: Option<String>,
    /// Known target note identity, when already resolved.
    pub target_note_id: Option<String>,
    /// Relation name.
    pub relation: String,
    /// Frontmatter source field.
    pub source_field: String,
}

/// Manifest candidate fields for Context notes (mirrors the validator input).
#[derive(Debug, Clone, Deserialize)]
pub struct CompileManifestCandidateInput {
    /// Stable managed-note identity.
    pub note_id: String,
    /// Logical relative path.
    pub relative_path: String,
    /// Python-canonicalized path used for collision detection.
    pub canonical_relative_path: String,
    /// Whether this candidate is a canonical Context note.
    pub is_context: bool,
    /// Context duplicate signature fields.
    pub identity: CompileContextIdentityInput,
    /// Forward supersede reference after Python string-only normalization.
    pub supersedes_context_id: Option<String>,
    /// Backlink supersede reference after Python string-only normalization.
    pub superseded_by_context_id: Option<String>,
}

/// Context duplicate signature fields (mirrors the validator input).
#[derive(Debug, Clone, Deserialize)]
pub struct CompileContextIdentityInput {
    /// Canonical recall scope text.
    pub scope: Option<String>,
    /// Optional project identity.
    pub project: Option<String>,
    /// Optional workspace identity.
    pub workspace_id: Option<String>,
    /// Optional agent identity.
    pub agent_id: Option<String>,
    /// Optional user identity.
    pub user_id: Option<String>,
    /// Optional session identity.
    pub session_id: Option<String>,
    /// Canonical content hash stored in Context frontmatter.
    pub content_hash: Option<String>,
}

/// Current analyzed source snapshot submitted to [`compile_plan`].
#[derive(Debug, Clone, Deserialize)]
pub struct CurrentSourceSnapshot {
    /// Analyzed current documents (order-independent; sorted internally).
    pub documents: Vec<CompileDocumentInput>,
}

/// Previously compiled state of one document.
#[derive(Debug, Clone, Deserialize)]
pub struct PreviousDocumentState {
    /// Stable note identity.
    pub note_id: String,
    /// Vault-relative managed path.
    pub relative_path: String,
    /// Rust-computed raw source hash of the compiled content.
    pub source_hash: String,
    /// Chunk content hashes in chunk-index order.
    pub chunk_hashes: Vec<String>,
    /// Canonical edge identifiers of the compiled document.
    pub edge_ids: Vec<String>,
}

/// Previous compiled state used as the incremental diff baseline.
#[derive(Debug, Clone, Deserialize)]
pub struct PreviousCompilationSnapshot {
    /// Embedding freshness key the previous compile applied.
    pub embedding_fingerprint_key: String,
    /// Previously compiled documents (order-independent; sorted internally).
    pub documents: Vec<PreviousDocumentState>,
}

/// Document-level plan action.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CompileDocumentAction {
    /// No previous compiled state exists.
    Added,
    /// Source hash differs from the previous compiled state.
    Updated,
    /// Content is unchanged; only embedding freshness requires work.
    EmbeddingOnly,
}

/// Chunk-level plan action.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CompileChunkAction {
    /// Chunk does not exist in the previous compiled state.
    Add,
    /// Chunk content hash changed.
    Update,
    /// Chunk content hash is unchanged.
    Keep,
}

/// Edge-level plan action.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CompileEdgeAction {
    /// Edge does not exist in the previous compiled state.
    Add,
    /// Edge is identical to the previous compiled state.
    Keep,
}

/// Edge target resolution outcome owned by the graph resolution authority.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CompileEdgeResolution {
    /// Target note proven uniquely by id, exact path, or link name.
    Resolved,
    /// Target matches multiple healthy notes.
    Ambiguous,
    /// Target is absent from the healthy set.
    Missing,
}

/// Embedding invalidation reason.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EmbeddingReason {
    /// New document produced new chunks.
    DocumentAdded,
    /// Chunk content hashes changed.
    ChunksChanged,
    /// Embedding model/policy freshness key changed.
    EmbeddingPolicyChanged,
    /// No embedding work is required.
    None,
}

/// Embedding work action.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EmbeddingAction {
    /// Re-embed the listed chunk indexes.
    Reembed,
    /// Remove embeddings for a removed document.
    Remove,
    /// No embedding work.
    None,
}

/// One chunk of an upsert plan with its diff action.
#[derive(Debug, Clone, Serialize)]
pub struct CompileChunkPlan {
    /// Deterministic chunk record produced by the chunking authority; ``None``
    /// when the caller provided chunk hashes directly.
    pub record: Option<ChunkRecord>,
    /// Rust-computed chunk content hash.
    pub content_hash: String,
    /// Diff action against the previous compiled state.
    pub action: CompileChunkAction,
}

/// One edge of an upsert plan with its diff and resolution outcome.
#[derive(Debug, Clone, Serialize)]
pub struct CompileEdgePlan {
    /// Canonical edge identifier.
    pub edge_id: String,
    /// Source note identity.
    pub source_note_id: String,
    /// Source note path.
    pub source_path: String,
    /// Explicit target note id carried by the extraction, when any.
    pub seed_target_note_id: Option<String>,
    /// Unresolved target path text.
    pub candidate_target_path: String,
    /// Relation name.
    pub relation: String,
    /// Compatibility confidence.
    pub confidence: f64,
    /// Source kind tag.
    pub source_kind: String,
    /// Diff action against the previous compiled state.
    pub action: CompileEdgeAction,
    /// Graph resolution authority outcome for the target.
    pub resolution: CompileEdgeResolution,
    /// Resolved target note identity when uniquely resolved.
    pub target_note_id: Option<String>,
}

/// Embedding invalidation for one document.
#[derive(Debug, Clone, Serialize)]
pub struct EmbeddingDocumentDelta {
    /// Embedding work action.
    pub action: EmbeddingAction,
    /// Invalidation reason.
    pub reason: EmbeddingReason,
    /// Chunk indexes requiring re-embedding (empty means every chunk).
    pub chunk_indexes: Vec<usize>,
}

/// Plan for one added/changed/embedding-stale document.
#[derive(Debug, Clone, Serialize)]
pub struct CompileDocumentUpsert {
    /// Vault-relative managed path.
    pub relative_path: String,
    /// Stable note identity.
    pub note_id: String,
    /// Rust-computed raw source hash of the analyzed text.
    pub source_hash: String,
    /// Note title.
    pub title: String,
    /// Alexandria note type tag.
    pub alexandria_type: String,
    /// Normalized frontmatter JSON.
    pub frontmatter: Value,
    /// Body text from the analysis stage.
    pub body: String,
    /// Diff action against the previous compiled state.
    pub action: CompileDocumentAction,
    /// Whether the manifest authority accepted this document for indexing.
    pub manifest_accepted: bool,
    /// Chunk plans in chunk-index order.
    pub chunks: Vec<CompileChunkPlan>,
    /// Edge plans in deterministic candidate order.
    pub edges: Vec<CompileEdgePlan>,
    /// Previous edge ids absent from the current candidates.
    pub removed_edge_ids: Vec<String>,
    /// Embedding invalidation for this document.
    pub embedding: EmbeddingDocumentDelta,
}

/// Plan for one document that vanished from the current snapshot.
#[derive(Debug, Clone, Serialize)]
pub struct CompileDocumentRemoval {
    /// Stable note identity of the removed document.
    pub note_id: String,
    /// Vault-relative managed path.
    pub relative_path: String,
}

/// One deterministic compile diagnostic (manifest authority output).
#[derive(Debug, Clone, Serialize)]
pub struct CompileDiagnostic {
    /// Candidate relative path.
    pub relative_path: String,
    /// Candidate context identity.
    pub context_id: String,
    /// Exact validator message (Python-compatible contract).
    pub message: String,
}

/// Typed deterministic plan produced by [`compile_plan`].
#[derive(Debug, Clone, Serialize)]
pub struct CompilePlan {
    /// Compile-plan contract version.
    pub contract_version: u16,
    /// Compile-plan semantics version.
    pub compiler_version: u16,
    /// Fingerprint of the compile policy.
    pub policy_version: String,
    /// Document upsert plans sorted by relative path.
    pub upserts: Vec<CompileDocumentUpsert>,
    /// Document removal plans sorted by relative path.
    pub removals: Vec<CompileDocumentRemoval>,
    /// Manifest diagnostics in validator order.
    pub diagnostics: Vec<CompileDiagnostic>,
    /// Deterministic fingerprint over the whole plan.
    pub plan_fingerprint: String,
}

/// Invalid compile input or an impossible plan invariant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompilePlanError {
    message: String,
}

impl CompilePlanError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl std::fmt::Display for CompilePlanError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}", self.message)
    }
}

impl std::error::Error for CompilePlanError {}

/// Compile one deterministic plan from the current and previous snapshots.
///
/// The plan treats an empty previous snapshot as a full compile and a
/// populated one as an incremental diff; there is no separate planning
/// implementation. Documents whose raw source hash is unchanged require no
/// document/chunk/edge work; their chunks are only re-embedded when the
/// embedding freshness key changed. A source hash change with identical chunk
/// hashes (metadata-only edit) produces a document update with zero embedding
/// work.
///
/// # Errors
///
/// Returns an error when inputs are internally inconsistent or the reused
/// chunking/extraction primitives reject the batch.
pub fn compile_plan(
    current: &CurrentSourceSnapshot,
    previous: &PreviousCompilationSnapshot,
    policy: &CompilePolicy,
) -> Result<CompilePlan, CompilePlanError> {
    validate_compile_policy(policy)?;
    let document_indexes = build_document_indexes(current, previous)?;
    let chunk_policy = ChunkPolicy::new(policy.chunk_max_chars, policy.chunk_overlap_chars)
        .map_err(|error| CompilePlanError::new(format!("COMPILE_POLICY_INVALID: {error}")))?;
    let healthy_notes = build_healthy_notes(&current.documents)?;
    let note_refs: Vec<&GraphSourceNote> = healthy_notes.iter().collect();
    let notes_by_id = indexed_notes_by_id(&note_refs);
    let notes_by_path = indexed_notes_by_path(&note_refs);
    let notes_by_link = notes_by_link_name(&note_refs);
    let manifest = validate_manifest(current);
    let graph = CompileGraphContext {
        notes_by_id: &notes_by_id,
        notes_by_path: &notes_by_path,
        notes_by_link: &notes_by_link,
        note_refs: &note_refs,
    };
    let (upserts, mut resolution_diagnostics) = build_upserts(
        &document_indexes,
        previous,
        policy,
        &chunk_policy,
        &manifest,
        &graph,
    )?;
    let removals = build_removals(&document_indexes);
    let mut diagnostics = manifest_diagnostics(manifest.result.issues);
    diagnostics.append(&mut resolution_diagnostics);

    let policy_version = sha256_text(&serde_json::to_string(policy).map_err(|error| {
        CompilePlanError::new(format!("COMPILE_PLAN_SERIALIZE_FAILED: {error}"))
    })?);
    let plan = CompilePlan {
        contract_version: COMPILE_PLAN_VERSION,
        compiler_version: COMPILE_PLAN_VERSION,
        policy_version,
        upserts,
        removals,
        diagnostics,
        plan_fingerprint: String::new(),
    };
    let plan_fingerprint = fingerprint_plan(&plan);
    Ok(CompilePlan {
        plan_fingerprint,
        ..plan
    })
}

fn validate_compile_policy(policy: &CompilePolicy) -> Result<(), CompilePlanError> {
    if policy.chunk_max_chars == 0 {
        return Err(CompilePlanError::new(
            "COMPILE_POLICY_INVALID: chunk_max_chars must be greater than zero",
        ));
    }
    if policy.embedding_fingerprint_key.trim().is_empty() {
        return Err(CompilePlanError::new(
            "COMPILE_POLICY_INVALID: embedding_fingerprint_key must not be blank",
        ));
    }
    Ok(())
}

fn build_document_indexes<'current, 'previous>(
    current: &'current CurrentSourceSnapshot,
    previous: &'previous PreviousCompilationSnapshot,
) -> Result<DocumentIndexes<'current, 'previous>, CompilePlanError> {
    let mut current_by_path = BTreeMap::new();
    for document in &current.documents {
        if current_by_path
            .insert(document.relative_path.clone(), document)
            .is_some()
        {
            return Err(CompilePlanError::new(format!(
                "COMPILE_INPUT_INVALID: duplicate current document path {}",
                document.relative_path
            )));
        }
    }
    let mut previous_by_path = BTreeMap::new();
    for state in &previous.documents {
        if previous_by_path
            .insert(state.relative_path.clone(), state)
            .is_some()
        {
            return Err(CompilePlanError::new(format!(
                "COMPILE_INPUT_INVALID: duplicate previous document path {}",
                state.relative_path
            )));
        }
    }
    Ok(DocumentIndexes {
        current_by_path,
        previous_by_path,
    })
}

fn build_healthy_notes(
    documents: &[CompileDocumentInput],
) -> Result<Vec<GraphSourceNote>, CompilePlanError> {
    let mut healthy_notes: Vec<GraphSourceNote> = Vec::with_capacity(documents.len());
    for document in documents {
        healthy_notes.push(GraphSourceNote {
            note_id: DocumentId::new(document.note_id.clone()).map_err(|error| {
                CompilePlanError::new(format!("COMPILE_INPUT_INVALID: {error}"))
            })?,
            relative_path: RelativeVaultPath::new(document.relative_path.clone()).map_err(
                |error| CompilePlanError::new(format!("COMPILE_INPUT_INVALID: {error}")),
            )?,
            alexandria_type: document.alexandria_type.clone(),
            title: document.title.clone(),
            status: document.status.clone(),
            project: None,
            aliases: document.aliases.clone(),
            index_status: GraphIndexStatus::Indexed,
        });
    }
    Ok(healthy_notes)
}

struct ManifestValidation {
    candidates: Vec<ContextReindexManifestCandidate>,
    result: ContextReindexManifestResult,
    accepted_candidate_keys: BTreeSet<(usize, String)>,
}

struct DocumentIndexes<'current, 'previous> {
    current_by_path: BTreeMap<String, &'current CompileDocumentInput>,
    previous_by_path: BTreeMap<String, &'previous PreviousDocumentState>,
}

struct CompileGraphContext<'maps, 'notes> {
    notes_by_id: &'maps BTreeMap<String, usize>,
    notes_by_path: &'maps BTreeMap<String, Vec<usize>>,
    notes_by_link: &'maps BTreeMap<String, Vec<usize>>,
    note_refs: &'maps [&'notes GraphSourceNote],
}

struct EdgePlans {
    edges: Vec<CompileEdgePlan>,
    removed_edge_ids: Vec<String>,
    diagnostics: Vec<CompileDiagnostic>,
}

fn validate_manifest(current: &CurrentSourceSnapshot) -> ManifestValidation {
    let manifest_candidates: Vec<ContextReindexManifestCandidate> = current
        .documents
        .iter()
        .filter_map(|document| document.manifest_candidate.as_ref().map(convert_candidate))
        .collect();
    let manifest_result = validate_context_reindex_manifest(&manifest_candidates);
    let accepted_candidate_keys: std::collections::BTreeSet<(usize, String)> = manifest_result
        .accepted_indices
        .iter()
        .filter_map(|index| {
            manifest_candidates
                .get(*index)
                .map(|candidate| (*index, candidate.canonical_relative_path.clone()))
        })
        .collect();
    ManifestValidation {
        candidates: manifest_candidates,
        result: manifest_result,
        accepted_candidate_keys,
    }
}

fn build_upserts(
    document_indexes: &DocumentIndexes<'_, '_>,
    previous: &PreviousCompilationSnapshot,
    policy: &CompilePolicy,
    chunk_policy: &ChunkPolicy,
    manifest: &ManifestValidation,
    graph: &CompileGraphContext<'_, '_>,
) -> Result<(Vec<CompileDocumentUpsert>, Vec<CompileDiagnostic>), CompilePlanError> {
    let mut upserts = Vec::new();
    let mut resolution_diagnostics = Vec::new();
    for (relative_path, document) in &document_indexes.current_by_path {
        let source_hash = document
            .text
            .as_deref()
            .map_or_else(|| document.source_hash.clone(), sha256_text);
        let previous_state = document_indexes
            .previous_by_path
            .get(relative_path)
            .copied();
        let Some((action, initial_embedding)) =
            document_action(previous_state, &source_hash, previous, policy)
        else {
            continue;
        };
        let manifest_accepted = document_manifest_accepted(document, manifest);
        let (chunks, changed_chunk_indexes) = build_chunk_plans(
            relative_path,
            document,
            previous_state,
            &source_hash,
            chunk_policy,
        )?;
        let EdgePlans {
            edges,
            removed_edge_ids,
            diagnostics: mut edge_diagnostics,
        } = build_edge_plans(relative_path, document, previous_state, graph)?;
        let embedding = embedding_for_action(action, initial_embedding, changed_chunk_indexes);
        resolution_diagnostics.append(&mut edge_diagnostics);
        upserts.push(CompileDocumentUpsert {
            relative_path: relative_path.clone(),
            note_id: document.note_id.clone(),
            source_hash,
            title: document.title.clone(),
            alexandria_type: document.alexandria_type.clone(),
            frontmatter: document.frontmatter.clone(),
            body: document.body.clone(),
            action,
            manifest_accepted,
            chunks,
            edges,
            removed_edge_ids,
            embedding,
        });
    }
    Ok((upserts, resolution_diagnostics))
}

fn document_action(
    previous_state: Option<&PreviousDocumentState>,
    source_hash: &str,
    previous: &PreviousCompilationSnapshot,
    policy: &CompilePolicy,
) -> Option<(CompileDocumentAction, EmbeddingDocumentDelta)> {
    match previous_state {
        None => Some((
            CompileDocumentAction::Added,
            EmbeddingDocumentDelta {
                action: EmbeddingAction::Reembed,
                reason: EmbeddingReason::DocumentAdded,
                chunk_indexes: Vec::new(),
            },
        )),
        Some(state) if state.source_hash == source_hash => {
            if state.chunk_hashes.is_empty() {
                Some((
                    CompileDocumentAction::EmbeddingOnly,
                    EmbeddingDocumentDelta {
                        action: EmbeddingAction::Reembed,
                        reason: EmbeddingReason::ChunksChanged,
                        chunk_indexes: Vec::new(),
                    },
                ))
            } else if previous.embedding_fingerprint_key == policy.embedding_fingerprint_key {
                None
            } else {
                Some((
                    CompileDocumentAction::EmbeddingOnly,
                    EmbeddingDocumentDelta {
                        action: EmbeddingAction::Reembed,
                        reason: EmbeddingReason::EmbeddingPolicyChanged,
                        chunk_indexes: Vec::new(),
                    },
                ))
            }
        }
        Some(_) => Some((
            CompileDocumentAction::Updated,
            EmbeddingDocumentDelta {
                action: EmbeddingAction::None,
                reason: EmbeddingReason::None,
                chunk_indexes: Vec::new(),
            },
        )),
    }
}

fn document_manifest_accepted(
    document: &CompileDocumentInput,
    manifest: &ManifestValidation,
) -> bool {
    document
        .manifest_candidate
        .as_ref()
        .is_none_or(|candidate| {
            manifest
                .candidates
                .iter()
                .enumerate()
                .any(|(index, accepted)| {
                    accepted.note_id == candidate.note_id
                        && accepted.relative_path == candidate.relative_path
                        && manifest
                            .accepted_candidate_keys
                            .contains(&(index, accepted.canonical_relative_path.clone()))
                })
        })
}

fn build_chunk_plans(
    relative_path: &str,
    document: &CompileDocumentInput,
    previous_state: Option<&PreviousDocumentState>,
    source_hash: &str,
    policy: &ChunkPolicy,
) -> Result<(Vec<CompileChunkPlan>, Vec<usize>), CompilePlanError> {
    let chunk_records: Vec<(Option<ChunkRecord>, String)> =
        if let Some(provided) = &document.provided_chunks {
            provided
                .iter()
                .map(|chunk| (None, chunk.content_hash.clone()))
                .collect()
        } else {
            chunk_document(relative_path, document, policy)?
                .into_iter()
                .map(|record| {
                    let hash = sha256_text(&record.content);
                    (Some(record), hash)
                })
                .collect()
        };
    let mut chunks = Vec::with_capacity(chunk_records.len());
    let mut changed_chunk_indexes = Vec::new();
    for (index, (record, content_hash)) in chunk_records.into_iter().enumerate() {
        let chunk_action = match previous_state {
            Some(state) if state.source_hash == source_hash => CompileChunkAction::Keep,
            Some(state) => match state.chunk_hashes.get(index) {
                Some(previous_hash) if previous_hash.as_str() == content_hash.as_str() => {
                    CompileChunkAction::Keep
                }
                Some(_) => {
                    changed_chunk_indexes.push(index);
                    CompileChunkAction::Update
                }
                None => {
                    changed_chunk_indexes.push(index);
                    CompileChunkAction::Add
                }
            },
            None => {
                changed_chunk_indexes.push(index);
                CompileChunkAction::Add
            }
        };
        chunks.push(CompileChunkPlan {
            record,
            content_hash,
            action: chunk_action,
        });
    }
    Ok((chunks, changed_chunk_indexes))
}

fn build_edge_plans(
    relative_path: &str,
    document: &CompileDocumentInput,
    previous_state: Option<&PreviousDocumentState>,
    graph: &CompileGraphContext<'_, '_>,
) -> Result<EdgePlans, CompilePlanError> {
    let edge_candidates: Vec<EdgeCandidate> = match &document.provided_edges {
        Some(provided) => provided
            .iter()
            .map(|edge| EdgeCandidate {
                edge_id: edge.edge_id.clone(),
                source_note_id: edge.source_note_id.clone(),
                source_path: edge.source_path.clone(),
                target_note_id: edge.target_note_id.clone(),
                target_path: edge.target_path.clone(),
                relation: edge.relation.clone(),
                confidence: edge.confidence,
                source_kind: crate::reference_extraction::EdgeSourceKind::Wikilink,
                identity_material: String::new(),
                reference_index: None,
            })
            .collect(),
        None => edge_candidates_for_document(relative_path, document)?,
    };
    let mut edges = Vec::with_capacity(edge_candidates.len());
    let mut removed_edge_ids = Vec::new();
    if let Some(state) = previous_state {
        let current_edge_ids: BTreeSet<&str> = edge_candidates
            .iter()
            .map(|candidate| candidate.edge_id.as_str())
            .collect();
        for previous_edge_id in &state.edge_ids {
            if !current_edge_ids.contains(previous_edge_id.as_str()) {
                removed_edge_ids.push(previous_edge_id.clone());
            }
        }
        removed_edge_ids.sort();
    }
    let mut resolution_diagnostics = Vec::new();
    for candidate in edge_candidates {
        let edge_action = match previous_state {
            Some(state) if state.edge_ids.iter().any(|id| id == &candidate.edge_id) => {
                CompileEdgeAction::Keep
            }
            _ => CompileEdgeAction::Add,
        };
        let resolution = resolve_target_reference(
            candidate.target_note_id.as_deref(),
            &candidate.target_path,
            graph.notes_by_id,
            graph.notes_by_path,
            graph.notes_by_link,
            graph.note_refs,
        );
        let (edge_resolution, resolved_target) = match resolution {
            TargetResolution::Resolved(note) => (
                CompileEdgeResolution::Resolved,
                Some(String::from(note.note_id.as_str())),
            ),
            TargetResolution::Ambiguous => (CompileEdgeResolution::Ambiguous, None),
            TargetResolution::Missing => (CompileEdgeResolution::Missing, None),
        };
        if edge_resolution != CompileEdgeResolution::Resolved {
            resolution_diagnostics.push(CompileDiagnostic {
                relative_path: relative_path.to_owned(),
                context_id: document.note_id.clone(),
                message: format!(
                    "{:?}: edge target {} was not uniquely resolved by the graph authority",
                    edge_resolution, candidate.target_path
                ),
            });
        }
        edges.push(CompileEdgePlan {
            edge_id: candidate.edge_id,
            source_note_id: candidate.source_note_id,
            source_path: candidate.source_path,
            seed_target_note_id: candidate.target_note_id,
            candidate_target_path: candidate.target_path,
            relation: candidate.relation,
            confidence: candidate.confidence,
            source_kind: format!("{:?}", candidate.source_kind).to_lowercase(),
            action: edge_action,
            resolution: edge_resolution,
            target_note_id: resolved_target,
        });
    }
    Ok(EdgePlans {
        edges,
        removed_edge_ids,
        diagnostics: resolution_diagnostics,
    })
}

fn embedding_for_action(
    action: CompileDocumentAction,
    initial: EmbeddingDocumentDelta,
    changed_chunk_indexes: Vec<usize>,
) -> EmbeddingDocumentDelta {
    match action {
        CompileDocumentAction::Added | CompileDocumentAction::EmbeddingOnly => initial,
        CompileDocumentAction::Updated if changed_chunk_indexes.is_empty() => {
            EmbeddingDocumentDelta {
                action: EmbeddingAction::None,
                reason: EmbeddingReason::None,
                chunk_indexes: Vec::new(),
            }
        }
        CompileDocumentAction::Updated => EmbeddingDocumentDelta {
            action: EmbeddingAction::Reembed,
            reason: EmbeddingReason::ChunksChanged,
            chunk_indexes: changed_chunk_indexes,
        },
    }
}

fn build_removals(document_indexes: &DocumentIndexes<'_, '_>) -> Vec<CompileDocumentRemoval> {
    document_indexes
        .previous_by_path
        .iter()
        .filter(|(relative_path, _)| {
            !document_indexes
                .current_by_path
                .contains_key(*relative_path)
        })
        .map(|(relative_path, state)| CompileDocumentRemoval {
            note_id: state.note_id.clone(),
            relative_path: relative_path.clone(),
        })
        .collect()
}

fn manifest_diagnostics(
    issues: Vec<crate::context_reindex_manifest::ContextReindexManifestIssue>,
) -> Vec<CompileDiagnostic> {
    issues
        .into_iter()
        .map(|issue| CompileDiagnostic {
            relative_path: issue.relative_path,
            context_id: issue.context_id,
            message: issue.message,
        })
        .collect()
}

fn fingerprint_plan(plan: &CompilePlan) -> String {
    let mut fingerprint_source = String::new();
    fingerprint_source.push_str(&plan.policy_version);
    fingerprint_source.push('\u{1f}');
    for upsert in &plan.upserts {
        fingerprint_source.push_str(&upsert.relative_path);
        fingerprint_source.push('\u{1e}');
        fingerprint_source.push_str(&upsert.note_id);
        fingerprint_source.push('\u{1e}');
        fingerprint_source.push_str(&upsert.source_hash);
        fingerprint_source.push('\u{1e}');
        for chunk in &upsert.chunks {
            fingerprint_source.push_str(&chunk.content_hash);
            fingerprint_source.push('\u{1d}');
        }
        fingerprint_source.push('\u{1e}');
        for edge in &upsert.edges {
            fingerprint_source.push_str(&edge.edge_id);
            fingerprint_source.push('\u{1d}');
        }
        fingerprint_source.push('\u{1e}');
        for edge_id in &upsert.removed_edge_ids {
            fingerprint_source.push_str(edge_id);
            fingerprint_source.push('\u{1d}');
        }
        fingerprint_source.push('\u{1e}');
        fingerprint_source.push_str(&serde_json::to_string(&upsert.embedding).unwrap_or_default());
        fingerprint_source.push('\u{1f}');
    }
    for removal in &plan.removals {
        fingerprint_source.push_str(&removal.relative_path);
        fingerprint_source.push('\u{1f}');
    }
    for diagnostic in &plan.diagnostics {
        fingerprint_source.push_str(&diagnostic.message);
        fingerprint_source.push('\u{1f}');
    }
    sha256_text(&fingerprint_source)
}

fn chunk_document(
    relative_path: &str,
    document: &CompileDocumentInput,
    policy: &ChunkPolicy,
) -> Result<Vec<ChunkRecord>, CompilePlanError> {
    let document_id = DocumentId::new(document.note_id.clone())
        .map_err(|error| CompilePlanError::new(format!("COMPILE_INPUT_INVALID: {error}")))?;
    let path = RelativeVaultPath::new(relative_path.to_string())
        .map_err(|error| CompilePlanError::new(format!("COMPILE_INPUT_INVALID: {error}")))?;
    let input = ChunkDocumentInput::new(
        document_id,
        path,
        document.title.clone(),
        document.body.clone(),
    )
    .map_err(|error| CompilePlanError::new(format!("COMPILE_CHUNK_FAILED: {error}")))?;
    let batch = ChunkBatch::new(*policy, vec![input])
        .map_err(|error| CompilePlanError::new(format!("COMPILE_CHUNK_FAILED: {error}")))?;
    let result = chunk_batch(batch)
        .map_err(|error| CompilePlanError::new(format!("COMPILE_CHUNK_FAILED: {error}")))?;
    let outcome = result
        .results
        .into_iter()
        .next()
        .ok_or_else(|| CompilePlanError::new("COMPILE_CHUNK_FAILED: empty chunk outcome"))?;
    match outcome {
        ChunkDocumentOutcome::Success { chunks, .. } => Ok(chunks),
        ChunkDocumentOutcome::Error { error, .. } => Err(CompilePlanError::new(format!(
            "COMPILE_CHUNK_FAILED: {:?} {}",
            error.code, error.message
        ))),
    }
}

fn edge_candidates_for_document(
    relative_path: &str,
    document: &CompileDocumentInput,
) -> Result<Vec<EdgeCandidate>, CompilePlanError> {
    let note_id = DocumentId::new(document.note_id.clone())
        .map_err(|error| CompilePlanError::new(format!("COMPILE_INPUT_INVALID: {error}")))?;
    let path = RelativeVaultPath::new(relative_path.to_string())
        .map_err(|error| CompilePlanError::new(format!("COMPILE_INPUT_INVALID: {error}")))?;
    let mut frontmatter_edges = Vec::with_capacity(document.edge_seeds.len());
    for seed in &document.edge_seeds {
        frontmatter_edges.push(
            FrontmatterEdgeInput::new(
                seed.target_path.clone(),
                seed.target_note_id.clone(),
                seed.relation.clone(),
                seed.source_field.clone(),
            )
            .map_err(|error| CompilePlanError::new(format!("COMPILE_INPUT_INVALID: {error}")))?,
        );
    }
    let input = ReferenceDocumentInput::new(
        note_id,
        path,
        String::from("Alexandria"),
        document.body.clone(),
        frontmatter_edges,
    )
    .map_err(|error| CompilePlanError::new(format!("COMPILE_EDGE_FAILED: {error}")))?;
    let batch = ReferenceBatch::new(vec![input])
        .map_err(|error| CompilePlanError::new(format!("COMPILE_EDGE_FAILED: {error}")))?;
    let result = extract_reference_batch(batch)
        .map_err(|error| CompilePlanError::new(format!("COMPILE_EDGE_FAILED: {error}")))?;
    let outcome = result
        .results
        .into_iter()
        .next()
        .ok_or_else(|| CompilePlanError::new("COMPILE_EDGE_FAILED: empty reference outcome"))?;
    Ok(outcome.edges)
}

fn convert_candidate(input: &CompileManifestCandidateInput) -> ContextReindexManifestCandidate {
    ContextReindexManifestCandidate {
        note_id: input.note_id.clone(),
        relative_path: input.relative_path.clone(),
        canonical_relative_path: input.canonical_relative_path.clone(),
        is_context: input.is_context,
        identity: crate::context_reindex_manifest::ContextReindexIdentity {
            scope: input.identity.scope.clone(),
            project: input.identity.project.clone(),
            workspace_id: input.identity.workspace_id.clone(),
            agent_id: input.identity.agent_id.clone(),
            user_id: input.identity.user_id.clone(),
            session_id: input.identity.session_id.clone(),
            content_hash: input.identity.content_hash.clone(),
        },
        supersedes_context_id: input.supersedes_context_id.clone(),
        superseded_by_context_id: input.superseded_by_context_id.clone(),
    }
}

/// One note participating in graph target resolution diagnostics.
#[derive(Debug, Clone, Deserialize)]
pub struct DiagnosticNoteInput {
    /// Stable note identity.
    pub note_id: String,
    /// Vault-relative managed path.
    pub relative_path: String,
    /// Current display title.
    pub title: String,
    /// Current lifecycle status.
    pub status: String,
    /// Relational-index status string ("indexed"/"stale"/"error"/"unindexed").
    pub index_status: String,
    /// Python-decoded aliases used by the link-name authority.
    pub aliases: Vec<String>,
}

/// One cached edge submitted for target resolution.
#[derive(Debug, Clone, Deserialize)]
pub struct DiagnosticEdgeInput {
    /// Canonical edge identifier.
    pub edge_id: String,
    /// Source note identity.
    pub source_note_id: String,
    /// Explicit target note id, when the index carried one.
    pub target_note_id: Option<String>,
    /// Target path text.
    pub target_path: String,
}

/// Outcome of one diagnostic target resolution.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DiagnosticTargetOutcome {
    /// Target resolved to one healthy indexed note.
    Resolved,
    /// Target exists but is not indexed healthy.
    TargetNotIndexed,
    /// Target matches multiple healthy notes.
    Ambiguous,
    /// Target is absent from the note set.
    Missing,
}

/// Structured resolution result for one cached edge.
#[derive(Debug, Clone, Serialize)]
pub struct DiagnosticEdgeResolution {
    /// Canonical edge identifier.
    pub edge_id: String,
    /// Resolution outcome.
    pub outcome: DiagnosticTargetOutcome,
    /// Resolved/existing target note identity when known.
    pub target_note_id: Option<String>,
    /// Resolved target path when resolved.
    pub target_path: Option<String>,
    /// Index status of an existing-but-unhealthy target.
    pub target_index_status: Option<String>,
    /// Candidate note ids for ambiguous or hinted outcomes.
    pub candidate_note_ids: Vec<String>,
    /// Candidate paths for ambiguous or hinted outcomes.
    pub candidate_paths: Vec<String>,
}

struct DiagnosticGraphContext<'maps, 'notes> {
    healthy_by_id: &'maps BTreeMap<String, usize>,
    healthy_by_path: &'maps BTreeMap<String, Vec<usize>>,
    healthy_by_link: &'maps BTreeMap<String, Vec<usize>>,
    all_by_id: &'maps BTreeMap<String, usize>,
    all_by_path: &'maps BTreeMap<String, usize>,
    note_refs: &'maps [&'notes GraphSourceNote],
}

/// Resolve cached edge targets through the single graph resolution authority.
///
/// The healthy set is every note whose ``index_status`` is ``indexed``;
/// normalization, link-name folding, and ambiguity judgment all run through the
/// same projection authority used by the compile pipeline, so Python and SQL
/// consumers never re-implement target resolution.
#[must_use]
pub fn resolve_diagnostic_targets(
    notes: &[DiagnosticNoteInput],
    edges: &[DiagnosticEdgeInput],
) -> Vec<DiagnosticEdgeResolution> {
    let healthy = healthy_diagnostic_notes(notes);
    let note_refs: Vec<&GraphSourceNote> = healthy.iter().collect();
    let healthy_by_id = indexed_notes_by_id(&note_refs);
    let healthy_by_path = indexed_notes_by_path(&note_refs);
    let healthy_by_link = notes_by_link_name(&note_refs);
    let (all_by_id, all_by_path) = all_diagnostic_note_indexes(notes);
    let graph = DiagnosticGraphContext {
        healthy_by_id: &healthy_by_id,
        healthy_by_path: &healthy_by_path,
        healthy_by_link: &healthy_by_link,
        all_by_id: &all_by_id,
        all_by_path: &all_by_path,
        note_refs: &note_refs,
    };
    edges
        .iter()
        .map(|edge| resolve_diagnostic_edge(edge, &graph, notes))
        .collect()
}

fn healthy_diagnostic_notes(notes: &[DiagnosticNoteInput]) -> Vec<GraphSourceNote> {
    let mut healthy = Vec::new();
    for note in notes {
        if note.index_status != "indexed" {
            continue;
        }
        let Ok(note_id) = DocumentId::new(note.note_id.clone()) else {
            continue;
        };
        let Ok(relative_path) = RelativeVaultPath::new(note.relative_path.clone()) else {
            continue;
        };
        healthy.push(GraphSourceNote {
            note_id,
            relative_path,
            alexandria_type: String::from("context"),
            title: note.title.clone(),
            status: note.status.clone(),
            project: None,
            aliases: note.aliases.clone(),
            index_status: GraphIndexStatus::Indexed,
        });
    }
    healthy
}

fn all_diagnostic_note_indexes(
    notes: &[DiagnosticNoteInput],
) -> (BTreeMap<String, usize>, BTreeMap<String, usize>) {
    let all_by_id = notes
        .iter()
        .enumerate()
        .map(|(index, note)| (note.note_id.clone(), index))
        .collect();
    let all_by_path = notes
        .iter()
        .enumerate()
        .map(|(index, note)| (canonical_path_key(&note.relative_path), index))
        .collect();
    (all_by_id, all_by_path)
}

fn resolve_diagnostic_edge(
    edge: &DiagnosticEdgeInput,
    graph: &DiagnosticGraphContext<'_, '_>,
    notes: &[DiagnosticNoteInput],
) -> DiagnosticEdgeResolution {
    let path_key = canonical_path_key(&edge.target_path);
    if let Some(id) = edge.target_note_id.as_ref() {
        return resolve_explicit_diagnostic_edge(edge, id, &path_key, graph, notes);
    }
    if let Some(index) = graph
        .healthy_by_path
        .get(&path_key)
        .and_then(|indexes| indexes.first().copied())
    {
        return resolved_diagnostic_edge(&edge.edge_id, graph.note_refs[index]);
    }
    if let Some(index) = graph.all_by_path.get(&path_key).copied() {
        return not_indexed_diagnostic_edge(&edge.edge_id, &notes[index]);
    }
    resolve_diagnostic_link(edge, graph)
}

fn resolve_explicit_diagnostic_edge(
    edge: &DiagnosticEdgeInput,
    id: &str,
    path_key: &str,
    graph: &DiagnosticGraphContext<'_, '_>,
    notes: &[DiagnosticNoteInput],
) -> DiagnosticEdgeResolution {
    // An explicit target id is authoritative: a missing id is never masked by
    // whatever note happens to sit at the target path.
    if let Some(index) = graph.healthy_by_id.get(id).copied() {
        return resolved_diagnostic_edge(&edge.edge_id, graph.note_refs[index]);
    }
    if let Some(index) = graph.all_by_id.get(id).copied() {
        return not_indexed_diagnostic_edge(&edge.edge_id, &notes[index]);
    }
    let path_hint = graph.all_by_path.get(path_key).map(|index| &notes[*index]);
    missing_diagnostic_edge(&edge.edge_id, path_hint)
}

fn resolve_diagnostic_link(
    edge: &DiagnosticEdgeInput,
    graph: &DiagnosticGraphContext<'_, '_>,
) -> DiagnosticEdgeResolution {
    match resolve_target_reference(
        None,
        &edge.target_path,
        graph.healthy_by_id,
        graph.healthy_by_path,
        graph.healthy_by_link,
        graph.note_refs,
    ) {
        TargetResolution::Resolved(note) => resolved_diagnostic_edge(&edge.edge_id, note),
        TargetResolution::Ambiguous => {
            let mut candidates = Vec::new();
            for candidate_name in candidate_link_names(&edge.target_path) {
                if let Some(indexes) = graph.healthy_by_link.get(&candidate_name) {
                    for index in indexes {
                        let note = graph.note_refs[*index];
                        candidates.push((
                            String::from(note.note_id.as_str()),
                            String::from(note.relative_path.as_str()),
                        ));
                    }
                }
            }
            candidates.sort();
            candidates.dedup();
            ambiguous_diagnostic_edge(&edge.edge_id, &candidates)
        }
        TargetResolution::Missing => missing_diagnostic_edge(&edge.edge_id, None),
    }
}

fn resolved_diagnostic_edge(edge_id: &str, note: &GraphSourceNote) -> DiagnosticEdgeResolution {
    DiagnosticEdgeResolution {
        edge_id: edge_id.to_owned(),
        outcome: DiagnosticTargetOutcome::Resolved,
        target_note_id: Some(String::from(note.note_id.as_str())),
        target_path: Some(String::from(note.relative_path.as_str())),
        target_index_status: None,
        candidate_note_ids: Vec::new(),
        candidate_paths: Vec::new(),
    }
}

fn not_indexed_diagnostic_edge(
    edge_id: &str,
    note: &DiagnosticNoteInput,
) -> DiagnosticEdgeResolution {
    DiagnosticEdgeResolution {
        edge_id: edge_id.to_owned(),
        outcome: DiagnosticTargetOutcome::TargetNotIndexed,
        target_note_id: Some(note.note_id.clone()),
        target_path: Some(note.relative_path.clone()),
        target_index_status: Some(note.index_status.clone()),
        candidate_note_ids: vec![note.note_id.clone()],
        candidate_paths: vec![note.relative_path.clone()],
    }
}

fn missing_diagnostic_edge(
    edge_id: &str,
    path_hint: Option<&DiagnosticNoteInput>,
) -> DiagnosticEdgeResolution {
    let (candidate_note_ids, candidate_paths) = path_hint
        .map_or((Vec::new(), Vec::new()), |note| {
            (vec![note.note_id.clone()], vec![note.relative_path.clone()])
        });
    DiagnosticEdgeResolution {
        edge_id: edge_id.to_owned(),
        outcome: DiagnosticTargetOutcome::Missing,
        target_note_id: None,
        target_path: None,
        target_index_status: None,
        candidate_note_ids,
        candidate_paths,
    }
}

fn ambiguous_diagnostic_edge(
    edge_id: &str,
    candidates: &[(String, String)],
) -> DiagnosticEdgeResolution {
    DiagnosticEdgeResolution {
        edge_id: edge_id.to_owned(),
        outcome: DiagnosticTargetOutcome::Ambiguous,
        target_note_id: None,
        target_path: None,
        target_index_status: None,
        candidate_note_ids: candidates
            .iter()
            .map(|(note_id, _)| note_id.clone())
            .collect(),
        candidate_paths: candidates.iter().map(|(_, path)| path.clone()).collect(),
    }
}
