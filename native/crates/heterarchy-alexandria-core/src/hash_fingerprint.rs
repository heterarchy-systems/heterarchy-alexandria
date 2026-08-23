//! Canonical SHA-256, embedding fingerprint, and deterministic change compute.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::{Display, Formatter};

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::ComputeContractVersion;
use crate::document_analysis::{DocumentId, RelativeVaultPath};

/// Version of the hash/fingerprint/change response schema.
pub const HASH_FINGERPRINT_VERSION: u16 = 1;

const MAX_DOCUMENTS_PER_BATCH: usize = 4_096;
const MAX_DOCUMENT_BYTES: usize = 64 * 1024 * 1024;
const MAX_BATCH_BYTES: usize = 256 * 1024 * 1024;
const MAX_IDENTITIES_PER_SET: usize = 1_000_000;

/// Embedding-generation identity fields preserved from the current Python contract.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmbeddingFingerprintInput {
    provider: String,
    model: String,
    provider_version: String,
    pooling_mode: String,
    normalize: bool,
    dimensions: i64,
    document_input_format: String,
}

impl EmbeddingFingerprintInput {
    /// Construct one exact embedding fingerprint without inventing new validation policy.
    #[must_use]
    pub const fn new(
        provider: String,
        model: String,
        provider_version: String,
        pooling_mode: String,
        normalize: bool,
        dimensions: i64,
        document_input_format: String,
    ) -> Self {
        Self {
            provider,
            model,
            provider_version,
            pooling_mode,
            normalize,
            dimensions,
            document_input_format,
        }
    }

    fn identity_payload(&self) -> BTreeMap<String, Value> {
        BTreeMap::from([
            ("dimensions".to_owned(), Value::from(self.dimensions)),
            (
                "document_input_format".to_owned(),
                Value::from(self.document_input_format.clone()),
            ),
            ("model".to_owned(), Value::from(self.model.clone())),
            ("normalize".to_owned(), Value::from(self.normalize)),
            (
                "pooling_mode".to_owned(),
                Value::from(self.pooling_mode.clone()),
            ),
            ("provider".to_owned(), Value::from(self.provider.clone())),
            (
                "provider_version".to_owned(),
                Value::from(self.provider_version.clone()),
            ),
        ])
    }
}

/// Previous values used only for deterministic change classification.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct PreviousComputeSnapshot {
    /// Previously persisted canonical content hash.
    pub content_hash: Option<String>,
    /// Previously persisted embedding fingerprint key.
    pub embedding_fingerprint_key: Option<String>,
    /// Previously accepted chunk identity set.
    pub chunk_identities: Option<Vec<String>>,
    /// Previously accepted graph edge identity set.
    pub edge_identities: Option<Vec<String>>,
}

/// Current optional fingerprint and canonical identity sets supplied by Python.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct CurrentComputeSnapshot {
    /// Current embedding generation strategy when fingerprint compute is requested.
    pub embedding_fingerprint: Option<EmbeddingFingerprintInput>,
    /// Caller-formatted timestamp used only for snapshot payload construction.
    pub indexed_at: Option<String>,
    /// Current chunk identities when set comparison is requested.
    pub chunk_identities: Option<Vec<String>>,
    /// Current edge identities when set comparison is requested.
    pub edge_identities: Option<Vec<String>>,
}

/// One already-read document and explicit comparison state.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HashDocumentInput {
    document_id: DocumentId,
    relative_path: RelativeVaultPath,
    text: String,
    embedding_fingerprint: Option<EmbeddingFingerprintInput>,
    indexed_at: Option<String>,
    previous: PreviousComputeSnapshot,
    current_chunk_identities: Option<Vec<String>>,
    current_edge_identities: Option<Vec<String>>,
}

impl HashDocumentInput {
    /// Construct one bounded hash/fingerprint/change request.
    ///
    /// # Errors
    ///
    /// Returns an error when text or identity collections exceed native safety bounds.
    pub fn new(
        document_id: DocumentId,
        relative_path: RelativeVaultPath,
        text: String,
        current: CurrentComputeSnapshot,
        previous: PreviousComputeSnapshot,
    ) -> Result<Self, HashBatchError> {
        if text.len() > MAX_DOCUMENT_BYTES {
            return Err(HashBatchError::new(format!(
                "document {} exceeds the {MAX_DOCUMENT_BYTES} byte hash limit",
                document_id.as_str()
            )));
        }
        for (name, identities) in [
            ("previous chunk", previous.chunk_identities.as_ref()),
            ("previous edge", previous.edge_identities.as_ref()),
            ("current chunk", current.chunk_identities.as_ref()),
            ("current edge", current.edge_identities.as_ref()),
        ] {
            if identities.is_some_and(|values| values.len() > MAX_IDENTITIES_PER_SET) {
                return Err(HashBatchError::new(format!(
                    "{name} identity set exceeds the {MAX_IDENTITIES_PER_SET} item limit"
                )));
            }
        }
        Ok(Self {
            document_id,
            relative_path,
            text,
            embedding_fingerprint: current.embedding_fingerprint,
            indexed_at: current.indexed_at,
            previous,
            current_chunk_identities: current.chunk_identities,
            current_edge_identities: current.edge_identities,
        })
    }
}

/// Coarse-grained hash and change request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HashBatch {
    documents: Vec<HashDocumentInput>,
}

impl HashBatch {
    /// Validate batch cardinality and aggregate document bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when deterministic safety bounds are exceeded.
    pub fn new(documents: Vec<HashDocumentInput>) -> Result<Self, HashBatchError> {
        if documents.len() > MAX_DOCUMENTS_PER_BATCH {
            return Err(HashBatchError::new(format!(
                "hash batch exceeds the {MAX_DOCUMENTS_PER_BATCH} item limit"
            )));
        }
        let total_bytes = documents.iter().try_fold(0_usize, |total, document| {
            total
                .checked_add(document.text.len())
                .ok_or_else(|| HashBatchError::new("hash batch byte count overflow"))
        })?;
        if total_bytes > MAX_BATCH_BYTES {
            return Err(HashBatchError::new(format!(
                "hash batch exceeds the {MAX_BATCH_BYTES} byte limit"
            )));
        }
        Ok(Self { documents })
    }
}

/// Invalid input or canonical JSON serialization failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HashBatchError {
    message: String,
}

impl HashBatchError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for HashBatchError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for HashBatchError {}

/// Exact current embedding identity and optional persisted snapshot payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct EmbeddingFingerprintResult {
    /// Timestamp-free identity payload with canonical key ordering.
    pub identity_payload: BTreeMap<String, Value>,
    /// Compact canonical JSON key matching `dumps_canonical_json`.
    pub key: String,
    /// Optional generated/indexed timestamp snapshot using caller-provided text.
    pub snapshot_payload: Option<BTreeMap<String, Value>>,
}

/// Change-report component in a fixed semantic order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ChangeComponent {
    /// Canonical UTF-8 content digest.
    ContentHash,
    /// Embedding generation strategy identity.
    EmbeddingFingerprint,
    /// Canonical set of chunk identities.
    ChunkIdentities,
    /// Canonical set of edge identities.
    EdgeIdentities,
}

/// Deterministic comparison state for one component.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ChangeState {
    /// No current value was supplied for comparison.
    NotCompared,
    /// Current value exists but no previous value was supplied.
    MissingPrevious,
    /// Previous and current values are equivalent.
    Unchanged,
    /// Previous and current values differ.
    Changed,
}

/// One typed component comparison.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ComponentChange {
    /// Compared component.
    pub component: ChangeComponent,
    /// Comparison outcome.
    pub state: ChangeState,
    /// Previous scalar value when applicable.
    pub previous_value: Option<String>,
    /// Current scalar value when applicable.
    pub current_value: Option<String>,
    /// Previous set cardinality when applicable.
    pub previous_count: Option<usize>,
    /// Current set cardinality when applicable.
    pub current_count: Option<usize>,
}

/// Deterministic change classification without lifecycle or persistence decisions.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ChangeReport {
    /// Components in the fixed order content, fingerprint, chunks, edges.
    pub components: Vec<ComponentChange>,
    /// Whether at least one compared component differs.
    pub any_changed: bool,
    /// Whether changed or missing previous state requires Python policy review.
    pub requires_refresh: bool,
}

/// Result for one document in request order.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HashDocumentResult {
    /// Caller-owned identity.
    pub document_id: DocumentId,
    /// Caller-owned path identity.
    pub relative_path: RelativeVaultPath,
    /// Exact SHA-256 hex digest of the input UTF-8 bytes.
    pub content_hash: String,
    /// Optional embedding fingerprint output.
    pub embedding_fingerprint: Option<EmbeddingFingerprintResult>,
    /// Pure deterministic comparison report.
    pub change_report: ChangeReport,
}

/// Coarse-grained hash/fingerprint response.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HashBatchResult {
    /// Python/Rust compute contract version.
    pub contract_version: u16,
    /// Hash/fingerprint response version.
    pub hashing_version: u16,
    /// Results in request order.
    pub results: Vec<HashDocumentResult>,
}

/// Compute exact hashes, embedding fingerprint keys, and comparison flags.
///
/// # Errors
///
/// Returns an error only when canonical JSON serialization fails.
pub fn compute_hash_batch(batch: HashBatch) -> Result<HashBatchResult, HashBatchError> {
    let mut results = Vec::with_capacity(batch.documents.len());
    for document in batch.documents {
        results.push(compute_document(document)?);
    }
    Ok(HashBatchResult {
        contract_version: ComputeContractVersion::CURRENT.value(),
        hashing_version: HASH_FINGERPRINT_VERSION,
        results,
    })
}

fn compute_document(document: HashDocumentInput) -> Result<HashDocumentResult, HashBatchError> {
    let HashDocumentInput {
        document_id,
        relative_path,
        text,
        embedding_fingerprint,
        indexed_at,
        previous,
        current_chunk_identities,
        current_edge_identities,
    } = document;
    let content_hash = sha256_text(&text);
    let embedding_fingerprint = embedding_fingerprint
        .map(|fingerprint| fingerprint_result(&fingerprint, indexed_at.as_deref()))
        .transpose()?;
    let current_fingerprint_key = embedding_fingerprint
        .as_ref()
        .map(|fingerprint| fingerprint.key.clone());
    let change_report = change_report(
        &previous,
        &content_hash,
        current_fingerprint_key.as_deref(),
        current_chunk_identities.as_deref(),
        current_edge_identities.as_deref(),
    );
    Ok(HashDocumentResult {
        document_id,
        relative_path,
        content_hash,
        embedding_fingerprint,
        change_report,
    })
}

/// Return the exact SHA-256 hex digest of UTF-8 text bytes.
#[must_use]
pub fn sha256_text(text: &str) -> String {
    format!("{:x}", Sha256::digest(text.as_bytes()))
}

fn fingerprint_result(
    fingerprint: &EmbeddingFingerprintInput,
    indexed_at: Option<&str>,
) -> Result<EmbeddingFingerprintResult, HashBatchError> {
    let identity_payload = fingerprint.identity_payload();
    let key = serde_json::to_string(&identity_payload).map_err(|error| {
        HashBatchError::new(format!(
            "embedding fingerprint serialization failed: {error}"
        ))
    })?;
    let snapshot_payload = indexed_at.map(|timestamp| {
        let mut payload = identity_payload.clone();
        payload.insert("generated_at".to_owned(), Value::from(timestamp));
        payload.insert("indexed_at".to_owned(), Value::from(timestamp));
        payload
    });
    Ok(EmbeddingFingerprintResult {
        identity_payload,
        key,
        snapshot_payload,
    })
}

fn change_report(
    previous: &PreviousComputeSnapshot,
    content_hash: &str,
    fingerprint_key: Option<&str>,
    current_chunk_identities: Option<&[String]>,
    current_edge_identities: Option<&[String]>,
) -> ChangeReport {
    let components = vec![
        scalar_change(
            ChangeComponent::ContentHash,
            previous.content_hash.as_deref(),
            Some(content_hash),
        ),
        scalar_change(
            ChangeComponent::EmbeddingFingerprint,
            previous.embedding_fingerprint_key.as_deref(),
            fingerprint_key,
        ),
        set_change(
            ChangeComponent::ChunkIdentities,
            previous.chunk_identities.as_deref(),
            current_chunk_identities,
        ),
        set_change(
            ChangeComponent::EdgeIdentities,
            previous.edge_identities.as_deref(),
            current_edge_identities,
        ),
    ];
    let any_changed = components
        .iter()
        .any(|component| component.state == ChangeState::Changed);
    let requires_refresh = components.iter().any(|component| {
        matches!(
            component.state,
            ChangeState::Changed | ChangeState::MissingPrevious
        )
    });
    ChangeReport {
        components,
        any_changed,
        requires_refresh,
    }
}

fn scalar_change(
    component: ChangeComponent,
    previous: Option<&str>,
    current: Option<&str>,
) -> ComponentChange {
    let state = comparison_state(previous, current);
    ComponentChange {
        component,
        state,
        previous_value: previous.map(str::to_owned),
        current_value: current.map(str::to_owned),
        previous_count: None,
        current_count: None,
    }
}

fn set_change(
    component: ChangeComponent,
    previous: Option<&[String]>,
    current: Option<&[String]>,
) -> ComponentChange {
    let previous_set = previous.map(canonical_identity_set);
    let current_set = current.map(canonical_identity_set);
    let state = comparison_state(previous_set.as_ref(), current_set.as_ref());
    ComponentChange {
        component,
        state,
        previous_value: None,
        current_value: None,
        previous_count: previous_set.as_ref().map(BTreeSet::len),
        current_count: current_set.as_ref().map(BTreeSet::len),
    }
}

fn comparison_state<T: PartialEq>(previous: Option<T>, current: Option<T>) -> ChangeState {
    match (previous, current) {
        (_, None) => ChangeState::NotCompared,
        (None, Some(_)) => ChangeState::MissingPrevious,
        (Some(left), Some(right)) if left == right => ChangeState::Unchanged,
        (Some(_), Some(_)) => ChangeState::Changed,
    }
}

fn canonical_identity_set(values: &[String]) -> BTreeSet<&str> {
    values.iter().map(String::as_str).collect()
}

#[cfg(test)]
mod tests {
    use super::{
        ChangeComponent, ChangeState, CurrentComputeSnapshot, EmbeddingFingerprintInput, HashBatch,
        HashDocumentInput, PreviousComputeSnapshot, compute_hash_batch, sha256_text,
    };
    use crate::document_analysis::{DocumentId, RelativeVaultPath};

    fn document(
        text: &str,
        fingerprint: Option<EmbeddingFingerprintInput>,
        previous: PreviousComputeSnapshot,
        current_chunks: Option<Vec<String>>,
        current_edges: Option<Vec<String>>,
    ) -> HashDocumentInput {
        let document_id = match DocumentId::new("case".to_owned()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid identity rejected: {error}"),
        };
        let relative_path = match RelativeVaultPath::new("Contexts/Case.md".to_owned()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid path rejected: {error}"),
        };
        let current = CurrentComputeSnapshot {
            embedding_fingerprint: fingerprint,
            indexed_at: Some("2026-08-22T00:00:00+09:00".to_owned()),
            chunk_identities: current_chunks,
            edge_identities: current_edges,
        };
        match HashDocumentInput::new(
            document_id,
            relative_path,
            text.to_owned(),
            current,
            previous,
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid hash input rejected: {error}"),
        }
    }

    fn fingerprint() -> EmbeddingFingerprintInput {
        EmbeddingFingerprintInput::new(
            "fastembed".to_owned(),
            "intfloat/multilingual-e5-small".to_owned(),
            "0.8.0".to_owned(),
            "mean".to_owned(),
            true,
            384,
            "passage: {text}".to_owned(),
        )
    }

    #[test]
    fn sha256_preserves_exact_utf8_and_line_ending_bytes() {
        assert_eq!(
            sha256_text("Hermes 기억\r\n"),
            "1a71e20855c7b8d743848746817ca0f4dc9d947a7748c0b3803612330f6d8648"
        );
        assert_ne!(sha256_text("line\n"), sha256_text("line\r\n"));
    }

    #[test]
    fn fingerprint_key_matches_sorted_compact_json() {
        let input = document(
            "body",
            Some(fingerprint()),
            PreviousComputeSnapshot::default(),
            None,
            None,
        );
        let batch = match HashBatch::new(vec![input]) {
            Ok(value) => value,
            Err(error) => unreachable!("valid batch rejected: {error}"),
        };
        let result = match compute_hash_batch(batch) {
            Ok(value) => value,
            Err(error) => unreachable!("hash compute failed: {error}"),
        };
        let Some(fingerprint) = &result.results[0].embedding_fingerprint else {
            unreachable!("fingerprint result is missing")
        };
        assert_eq!(
            fingerprint.key,
            r#"{"dimensions":384,"document_input_format":"passage: {text}","model":"intfloat/multilingual-e5-small","normalize":true,"pooling_mode":"mean","provider":"fastembed","provider_version":"0.8.0"}"#
        );
    }

    #[test]
    fn change_components_are_ordered_and_set_comparison_is_order_independent() {
        let content_hash = sha256_text("same");
        let previous_fingerprint = {
            let input = document(
                "same",
                Some(fingerprint()),
                PreviousComputeSnapshot::default(),
                None,
                None,
            );
            let batch = match HashBatch::new(vec![input]) {
                Ok(value) => value,
                Err(error) => unreachable!("valid batch rejected: {error}"),
            };
            let result = match compute_hash_batch(batch) {
                Ok(value) => value,
                Err(error) => unreachable!("hash compute failed: {error}"),
            };
            let Some(value) = &result.results[0].embedding_fingerprint else {
                unreachable!("fingerprint result is missing")
            };
            value.key.clone()
        };
        let previous = PreviousComputeSnapshot {
            content_hash: Some(content_hash),
            embedding_fingerprint_key: Some(previous_fingerprint),
            chunk_identities: Some(vec!["b".to_owned(), "a".to_owned(), "a".to_owned()]),
            edge_identities: Some(vec!["edge-1".to_owned()]),
        };
        let input = document(
            "same",
            Some(fingerprint()),
            previous,
            Some(vec!["a".to_owned(), "b".to_owned()]),
            Some(vec!["edge-2".to_owned()]),
        );
        let batch = match HashBatch::new(vec![input]) {
            Ok(value) => value,
            Err(error) => unreachable!("valid batch rejected: {error}"),
        };
        let result = match compute_hash_batch(batch) {
            Ok(value) => value,
            Err(error) => unreachable!("hash compute failed: {error}"),
        };
        let report = &result.results[0].change_report;
        let components = report
            .components
            .iter()
            .map(|change| (change.component, change.state))
            .collect::<Vec<_>>();
        assert_eq!(
            components,
            vec![
                (ChangeComponent::ContentHash, ChangeState::Unchanged),
                (
                    ChangeComponent::EmbeddingFingerprint,
                    ChangeState::Unchanged
                ),
                (ChangeComponent::ChunkIdentities, ChangeState::Unchanged),
                (ChangeComponent::EdgeIdentities, ChangeState::Changed),
            ]
        );
        assert!(report.any_changed);
        assert!(report.requires_refresh);
    }
}
