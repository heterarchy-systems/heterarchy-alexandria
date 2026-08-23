//! Bounded candidate discovery for memory reconciliation.
//!
//! This module computes evidence and candidate groups only. Final semantic relation
//! classification, lifecycle decisions, review, and persistence remain Python-owned.

use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::{Display, Formatter};

use serde::Serialize;

use crate::ComputeContractVersion;
use crate::retrieval_kernel::cosine_similarity;

/// Version of the reconciliation candidate discovery contract.
pub const RECONCILIATION_CANDIDATE_VERSION: u16 = 1;

const MAX_ITEMS: usize = 1_000_000;
const MAX_ID_BYTES: usize = 4_096;
const MAX_HASH_BYTES: usize = 4_096;
const MAX_BLOCK_KEY_BYTES: usize = 16 * 1_024;
const MAX_RELATION_IDS_PER_ITEM: usize = 100_000;
const MAX_VECTOR_DIMENSIONS: usize = 65_536;

/// Candidate generation policy supplied explicitly by Python.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CandidatePolicy {
    /// Minimum cosine similarity needed for vector evidence.
    pub vector_similarity_threshold: f64,
    /// Minimum graph-neighborhood Jaccard similarity needed for graph evidence.
    pub graph_similarity_threshold: f64,
    /// Maximum members permitted in one caller-provided comparison block.
    pub max_block_size: usize,
    /// Maximum retained candidate pairs incident to one item.
    pub max_candidates_per_item: usize,
}

impl CandidatePolicy {
    /// Construct a bounded candidate policy.
    ///
    /// # Errors
    ///
    /// Returns an input error when thresholds are non-finite/outside `[0, 1]` or limits are zero.
    pub fn new(
        vector_similarity_threshold: f64,
        graph_similarity_threshold: f64,
        max_block_size: usize,
        max_candidates_per_item: usize,
    ) -> Result<Self, CandidateEngineError> {
        validate_probability("vector_similarity_threshold", vector_similarity_threshold)?;
        validate_probability("graph_similarity_threshold", graph_similarity_threshold)?;
        if max_block_size == 0 {
            return Err(CandidateEngineError::new(
                "max_block_size must be greater than zero",
            ));
        }
        if max_candidates_per_item == 0 {
            return Err(CandidateEngineError::new(
                "max_candidates_per_item must be greater than zero",
            ));
        }
        Ok(Self {
            vector_similarity_threshold,
            graph_similarity_threshold,
            max_block_size,
            max_candidates_per_item,
        })
    }
}

/// Open-ended validity interval already normalized by Python into epoch microseconds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TemporalInterval {
    /// Inclusive lower bound.
    pub valid_from_micros: Option<i64>,
    /// Inclusive upper bound.
    pub valid_to_micros: Option<i64>,
}

impl TemporalInterval {
    /// Construct an interval whose lower bound does not exceed its upper bound.
    ///
    /// # Errors
    ///
    /// Returns an input error when both bounds exist and are reversed.
    pub fn new(
        valid_from_micros: Option<i64>,
        valid_to_micros: Option<i64>,
    ) -> Result<Self, CandidateEngineError> {
        if let (Some(start), Some(end)) = (valid_from_micros, valid_to_micros)
            && start > end
        {
            return Err(CandidateEngineError::new(
                "valid_from_micros must not exceed valid_to_micros",
            ));
        }
        Ok(Self {
            valid_from_micros,
            valid_to_micros,
        })
    }
}

/// One item participating in bounded candidate discovery.
#[derive(Debug, Clone, PartialEq)]
pub struct ReconciliationItem {
    /// Stable Context/candidate identity.
    pub item_id: String,
    /// Existing canonical content hash when available.
    pub content_hash: Option<String>,
    /// Optional embedding already computed outside this engine.
    pub embedding: Option<Vec<f64>>,
    /// Explicit validity interval.
    pub temporal_interval: TemporalInterval,
    /// Caller-provided blocking keys used to bound vector/large-set comparison work.
    pub blocking_keys: Vec<String>,
    /// Stable IDs of structural graph neighbors.
    pub graph_neighbors: Vec<String>,
    /// Stable IDs in the item's supersedes/lineage ancestry.
    pub lineage_ancestors: Vec<String>,
}

impl ReconciliationItem {
    /// Validate and construct one candidate-discovery item.
    ///
    /// # Errors
    ///
    /// Returns a typed input error for invalid IDs, vectors, or excessive relation inputs.
    pub fn new(
        item_id: String,
        content_hash: Option<String>,
        embedding: Option<Vec<f64>>,
        temporal_interval: TemporalInterval,
        blocking_keys: Vec<String>,
        graph_neighbors: Vec<String>,
        lineage_ancestors: Vec<String>,
    ) -> Result<Self, CandidateEngineError> {
        validate_text("item_id", &item_id, MAX_ID_BYTES, false)?;
        if let Some(value) = &content_hash {
            validate_text("content_hash", value, MAX_HASH_BYTES, false)?;
        }
        if let Some(values) = &embedding {
            if values.is_empty() || values.len() > MAX_VECTOR_DIMENSIONS {
                return Err(CandidateEngineError::new(format!(
                    "embedding dimensions must be in 1..={MAX_VECTOR_DIMENSIONS}"
                )));
            }
            if values.iter().any(|value| !value.is_finite()) {
                return Err(CandidateEngineError::new(
                    "embedding values must all be finite",
                ));
            }
        }
        validate_text_collection("blocking_keys", &blocking_keys, MAX_BLOCK_KEY_BYTES)?;
        validate_relation_ids("graph_neighbors", &graph_neighbors)?;
        validate_relation_ids("lineage_ancestors", &lineage_ancestors)?;
        Ok(Self {
            item_id,
            content_hash,
            embedding,
            temporal_interval,
            blocking_keys,
            graph_neighbors,
            lineage_ancestors,
        })
    }
}

/// One exact content-hash duplicate group without quadratic pair expansion.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ExactDuplicateGroup {
    /// Shared canonical content hash.
    pub content_hash: String,
    /// Member IDs ordered lexicographically.
    pub item_ids: Vec<String>,
}

/// Evidence reason emitted by pure candidate discovery.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CandidateReason {
    /// Canonical content hashes are identical.
    ExactContentHash,
    /// Cosine similarity met the explicit vector threshold.
    VectorSimilarity,
    /// Validity intervals overlap under current Python-compatible interval semantics.
    TemporalOverlap,
    /// Graph-neighborhood Jaccard similarity met the explicit threshold.
    GraphNeighborhood,
    /// One item occurs in the other's lineage ancestry or they share lineage ancestry.
    LineageStructure,
}

/// Structural lineage evidence without assigning a semantic memory relation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LineageEvidence {
    /// Neither direct nor shared ancestry was observed.
    None,
    /// Left lists right as an ancestor.
    LeftDescendsFromRight,
    /// Right lists left as an ancestor.
    RightDescendsFromLeft,
    /// Both share at least one lineage ancestor.
    SharedAncestor,
}

/// One evidence-rich candidate pair for Python policy/review.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CandidatePair {
    /// Lexicographically smaller identity.
    pub left_id: String,
    /// Lexicographically larger identity.
    pub right_id: String,
    /// Whether canonical content hashes are exactly equal.
    pub exact_content_hash: bool,
    /// Optional cosine similarity when both vectors have equal dimensions.
    pub vector_similarity: Option<f64>,
    /// Python-compatible open-ended interval overlap.
    pub temporal_overlap: bool,
    /// Jaccard similarity over graph-neighbor identity sets.
    pub graph_similarity: f64,
    /// Structural lineage evidence only.
    pub lineage: LineageEvidence,
    /// Deterministic maximum evidence score used only for candidate ordering.
    pub candidate_score: f64,
    /// Ordered evidence reasons; not a final relation classification.
    pub reasons: Vec<CandidateReason>,
}

/// One connected component over retained candidate pairs.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CandidateCluster {
    /// Stable cluster index after deterministic component ordering.
    pub cluster_index: usize,
    /// Member identities ordered lexicographically.
    pub item_ids: Vec<String>,
}

/// Metrics exposing bounded work and reduction behavior.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct CandidateMetrics {
    /// Number of source items.
    pub input_items: usize,
    /// Unique comparison pairs considered after blocking/structural generation.
    pub comparison_pairs: usize,
    /// Candidate pairs before per-item cap enforcement.
    pub qualifying_pairs: usize,
    /// Retained pairs after deterministic per-item caps.
    pub retained_pairs: usize,
    /// Number of exact duplicate groups.
    pub exact_duplicate_groups: usize,
}

/// Complete pure candidate-discovery result.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CandidateEngineResult {
    /// Coarse Python/Rust contract version.
    pub contract_version: u16,
    /// Candidate engine version.
    pub candidate_version: u16,
    /// Exact hash groups represented without all-pairs expansion.
    pub exact_duplicate_groups: Vec<ExactDuplicateGroup>,
    /// Evidence-rich pairs for Python-owned semantic policy.
    pub candidate_pairs: Vec<CandidatePair>,
    /// Connected candidate groups for bulk review/processing.
    pub clusters: Vec<CandidateCluster>,
    /// Bounded-work metrics.
    pub metrics: CandidateMetrics,
}

/// Candidate engine input or invariant failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CandidateEngineError {
    message: String,
}

impl CandidateEngineError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for CandidateEngineError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for CandidateEngineError {}

/// Discover reconciliation candidates without making final semantic relation decisions.
///
/// # Errors
///
/// Returns an error for duplicate item IDs, oversized blocks, invalid dimensions, or excessive
/// input counts. Candidate comparison remains bounded by caller-provided blocks and explicit
/// graph/lineage edges rather than naive global all-pairs expansion.
pub fn discover_candidates(
    items: &[ReconciliationItem],
    policy: CandidatePolicy,
) -> Result<CandidateEngineResult, CandidateEngineError> {
    if items.len() > MAX_ITEMS {
        return Err(CandidateEngineError::new(format!(
            "item count exceeds the {MAX_ITEMS} limit"
        )));
    }
    let id_to_index = unique_item_index(items)?;
    let exact_duplicate_groups = exact_duplicate_groups(items);
    let comparison_pairs = comparison_pair_indexes(items, &id_to_index, policy.max_block_size)?;
    let qualifying = comparison_pairs
        .iter()
        .filter_map(|&(left, right)| qualifying_pair(&items[left], &items[right], policy))
        .collect::<Vec<_>>();
    let qualifying_count = qualifying.len();
    let candidate_pairs = enforce_per_item_cap(qualifying, policy.max_candidates_per_item);
    let clusters = clusters_from_pairs(&candidate_pairs);
    let metrics = CandidateMetrics {
        input_items: items.len(),
        comparison_pairs: comparison_pairs.len(),
        qualifying_pairs: qualifying_count,
        retained_pairs: candidate_pairs.len(),
        exact_duplicate_groups: exact_duplicate_groups.len(),
    };
    Ok(CandidateEngineResult {
        contract_version: ComputeContractVersion::CURRENT.value(),
        candidate_version: RECONCILIATION_CANDIDATE_VERSION,
        exact_duplicate_groups,
        candidate_pairs,
        clusters,
        metrics,
    })
}

fn unique_item_index(
    items: &[ReconciliationItem],
) -> Result<BTreeMap<String, usize>, CandidateEngineError> {
    let mut index = BTreeMap::new();
    for (position, item) in items.iter().enumerate() {
        if index.insert(item.item_id.clone(), position).is_some() {
            return Err(CandidateEngineError::new(format!(
                "duplicate item_id: {}",
                item.item_id
            )));
        }
    }
    Ok(index)
}

fn exact_duplicate_groups(items: &[ReconciliationItem]) -> Vec<ExactDuplicateGroup> {
    let mut groups = BTreeMap::<String, Vec<String>>::new();
    for item in items {
        if let Some(content_hash) = &item.content_hash {
            groups
                .entry(content_hash.clone())
                .or_default()
                .push(item.item_id.clone());
        }
    }
    groups
        .into_iter()
        .filter_map(|(content_hash, mut item_ids)| {
            if item_ids.len() < 2 {
                return None;
            }
            item_ids.sort();
            Some(ExactDuplicateGroup {
                content_hash,
                item_ids,
            })
        })
        .collect()
}

fn comparison_pair_indexes(
    items: &[ReconciliationItem],
    id_to_index: &BTreeMap<String, usize>,
    max_block_size: usize,
) -> Result<BTreeSet<(usize, usize)>, CandidateEngineError> {
    let mut pairs = BTreeSet::new();
    let mut blocks = BTreeMap::<String, Vec<usize>>::new();
    let mut hashes = BTreeMap::<String, Vec<usize>>::new();
    for (index, item) in items.iter().enumerate() {
        for key in &item.blocking_keys {
            blocks.entry(key.clone()).or_default().push(index);
        }
        if let Some(content_hash) = &item.content_hash {
            hashes.entry(content_hash.clone()).or_default().push(index);
        }
        add_relation_pairs(index, &item.graph_neighbors, id_to_index, &mut pairs);
        add_relation_pairs(index, &item.lineage_ancestors, id_to_index, &mut pairs);
    }
    for (key, members) in blocks {
        if members.len() > max_block_size {
            return Err(CandidateEngineError::new(format!(
                "blocking key {key:?} has {} members, exceeding max_block_size {max_block_size}",
                members.len()
            )));
        }
        add_all_pairs(&members, &mut pairs);
    }
    // Exact duplicate groups are represented without quadratic output. Compare each member with
    // one stable representative so every duplicate participates in evidence/clustering in O(n).
    for members in hashes.values() {
        let mut stable_members = members.clone();
        stable_members.sort_by(|left, right| items[*left].item_id.cmp(&items[*right].item_id));
        if let Some((&representative, rest)) = stable_members.split_first() {
            for &member in rest {
                pairs.insert(ordered_pair(representative, member));
            }
        }
    }
    Ok(pairs)
}

fn add_relation_pairs(
    source_index: usize,
    relation_ids: &[String],
    id_to_index: &BTreeMap<String, usize>,
    pairs: &mut BTreeSet<(usize, usize)>,
) {
    for target_id in relation_ids {
        if let Some(&target_index) = id_to_index.get(target_id)
            && source_index != target_index
        {
            pairs.insert(ordered_pair(source_index, target_index));
        }
    }
}

fn add_all_pairs(members: &[usize], pairs: &mut BTreeSet<(usize, usize)>) {
    for (offset, &left) in members.iter().enumerate() {
        for &right in &members[offset + 1..] {
            if left != right {
                pairs.insert(ordered_pair(left, right));
            }
        }
    }
}

const fn ordered_pair(left: usize, right: usize) -> (usize, usize) {
    if left < right {
        (left, right)
    } else {
        (right, left)
    }
}

fn qualifying_pair(
    left: &ReconciliationItem,
    right: &ReconciliationItem,
    policy: CandidatePolicy,
) -> Option<CandidatePair> {
    let (left, right) = if left.item_id <= right.item_id {
        (left, right)
    } else {
        (right, left)
    };
    let exact_content_hash = left.content_hash.is_some() && left.content_hash == right.content_hash;
    let vector_similarity =
        vector_similarity(left.embedding.as_deref(), right.embedding.as_deref());
    let temporal_overlap = intervals_overlap(left.temporal_interval, right.temporal_interval);
    let graph_similarity = jaccard_similarity(&left.graph_neighbors, &right.graph_neighbors);
    let lineage = lineage_evidence(left, right);

    let mut reasons = Vec::new();
    if exact_content_hash {
        reasons.push(CandidateReason::ExactContentHash);
    }
    if vector_similarity.is_some_and(|score| score >= policy.vector_similarity_threshold) {
        reasons.push(CandidateReason::VectorSimilarity);
    }
    if temporal_overlap {
        reasons.push(CandidateReason::TemporalOverlap);
    }
    if graph_similarity >= policy.graph_similarity_threshold && graph_similarity > 0.0 {
        reasons.push(CandidateReason::GraphNeighborhood);
    }
    if lineage != LineageEvidence::None {
        reasons.push(CandidateReason::LineageStructure);
    }

    let has_discovery_signal = exact_content_hash
        || vector_similarity.is_some_and(|score| score >= policy.vector_similarity_threshold)
        || (graph_similarity >= policy.graph_similarity_threshold && graph_similarity > 0.0)
        || lineage != LineageEvidence::None;
    if !has_discovery_signal {
        return None;
    }
    let vector_score = vector_similarity.unwrap_or(0.0).clamp(0.0, 1.0);
    let lineage_score = if lineage == LineageEvidence::None {
        0.0
    } else {
        1.0
    };
    let candidate_score = if exact_content_hash {
        1.0
    } else {
        vector_score.max(graph_similarity).max(lineage_score)
    };
    Some(CandidatePair {
        left_id: left.item_id.clone(),
        right_id: right.item_id.clone(),
        exact_content_hash,
        vector_similarity,
        temporal_overlap,
        graph_similarity,
        lineage,
        candidate_score,
        reasons,
    })
}

fn vector_similarity(left: Option<&[f64]>, right: Option<&[f64]>) -> Option<f64> {
    match (left, right) {
        (Some(left_values), Some(right_values)) if left_values.len() == right_values.len() => {
            Some(cosine_similarity(left_values, right_values))
        }
        _ => None,
    }
}

const fn intervals_overlap(left: TemporalInterval, right: TemporalInterval) -> bool {
    if let (Some(left_to), Some(right_from)) = (left.valid_to_micros, right.valid_from_micros)
        && left_to < right_from
    {
        return false;
    }
    !matches!(
        (right.valid_to_micros, left.valid_from_micros),
        (Some(right_to), Some(left_from)) if right_to < left_from
    )
}

fn jaccard_similarity(left: &[String], right: &[String]) -> f64 {
    let left_set = left.iter().collect::<BTreeSet<_>>();
    let right_set = right.iter().collect::<BTreeSet<_>>();
    let union = left_set.union(&right_set).count();
    if union == 0 {
        return 0.0;
    }
    let intersection = left_set.intersection(&right_set).count();
    let Ok(intersection_count) = u32::try_from(intersection) else {
        return 0.0;
    };
    let Ok(union_count) = u32::try_from(union) else {
        return 0.0;
    };
    f64::from(intersection_count) / f64::from(union_count)
}

fn lineage_evidence(left: &ReconciliationItem, right: &ReconciliationItem) -> LineageEvidence {
    if left
        .lineage_ancestors
        .iter()
        .any(|item| item == &right.item_id)
    {
        return LineageEvidence::LeftDescendsFromRight;
    }
    if right
        .lineage_ancestors
        .iter()
        .any(|item| item == &left.item_id)
    {
        return LineageEvidence::RightDescendsFromLeft;
    }
    let left_set = left.lineage_ancestors.iter().collect::<BTreeSet<_>>();
    let right_set = right.lineage_ancestors.iter().collect::<BTreeSet<_>>();
    if left_set.is_disjoint(&right_set) {
        LineageEvidence::None
    } else {
        LineageEvidence::SharedAncestor
    }
}

fn enforce_per_item_cap(
    mut candidates: Vec<CandidatePair>,
    max_candidates_per_item: usize,
) -> Vec<CandidatePair> {
    candidates.sort_by(candidate_order);
    let mut counts = BTreeMap::<String, usize>::new();
    let mut retained = Vec::new();
    for candidate in candidates {
        let left_count = counts.get(&candidate.left_id).copied().unwrap_or(0);
        let right_count = counts.get(&candidate.right_id).copied().unwrap_or(0);
        if left_count >= max_candidates_per_item || right_count >= max_candidates_per_item {
            continue;
        }
        *counts.entry(candidate.left_id.clone()).or_default() += 1;
        *counts.entry(candidate.right_id.clone()).or_default() += 1;
        retained.push(candidate);
    }
    retained
}

fn candidate_order(left: &CandidatePair, right: &CandidatePair) -> Ordering {
    right
        .candidate_score
        .total_cmp(&left.candidate_score)
        .then_with(|| left.left_id.cmp(&right.left_id))
        .then_with(|| left.right_id.cmp(&right.right_id))
}

fn clusters_from_pairs(pairs: &[CandidatePair]) -> Vec<CandidateCluster> {
    let mut adjacency = BTreeMap::<String, BTreeSet<String>>::new();
    for pair in pairs {
        adjacency
            .entry(pair.left_id.clone())
            .or_default()
            .insert(pair.right_id.clone());
        adjacency
            .entry(pair.right_id.clone())
            .or_default()
            .insert(pair.left_id.clone());
    }
    let mut seen = BTreeSet::new();
    let mut components = Vec::<Vec<String>>::new();
    for start in adjacency.keys() {
        if seen.contains(start) {
            continue;
        }
        let mut stack = vec![start.clone()];
        let mut component = Vec::new();
        seen.insert(start.clone());
        while let Some(current) = stack.pop() {
            component.push(current.clone());
            if let Some(neighbors) = adjacency.get(&current) {
                for neighbor in neighbors.iter().rev() {
                    if seen.insert(neighbor.clone()) {
                        stack.push(neighbor.clone());
                    }
                }
            }
        }
        component.sort();
        components.push(component);
    }
    components.sort();
    components
        .into_iter()
        .enumerate()
        .map(|(cluster_index, item_ids)| CandidateCluster {
            cluster_index,
            item_ids,
        })
        .collect()
}

fn validate_probability(name: &str, value: f64) -> Result<(), CandidateEngineError> {
    if !value.is_finite() || !(0.0..=1.0).contains(&value) {
        return Err(CandidateEngineError::new(format!(
            "{name} must be finite and within [0, 1]"
        )));
    }
    Ok(())
}

fn validate_text(
    name: &str,
    value: &str,
    max_bytes: usize,
    allow_empty: bool,
) -> Result<(), CandidateEngineError> {
    if (!allow_empty && value.trim().is_empty()) || value.len() > max_bytes || value.contains('\0')
    {
        return Err(CandidateEngineError::new(format!("invalid {name}")));
    }
    Ok(())
}

fn validate_text_collection(
    name: &str,
    values: &[String],
    max_bytes: usize,
) -> Result<(), CandidateEngineError> {
    if values.len() > MAX_RELATION_IDS_PER_ITEM {
        return Err(CandidateEngineError::new(format!(
            "{name} exceeds the {MAX_RELATION_IDS_PER_ITEM} item limit"
        )));
    }
    for value in values {
        validate_text(name, value, max_bytes, false)?;
    }
    Ok(())
}

fn validate_relation_ids(name: &str, values: &[String]) -> Result<(), CandidateEngineError> {
    validate_text_collection(name, values, MAX_ID_BYTES)
}

#[cfg(test)]
mod tests {
    use super::{
        CandidatePolicy, LineageEvidence, ReconciliationItem, TemporalInterval, discover_candidates,
    };

    fn item(
        item_id: &str,
        content_hash: Option<&str>,
        embedding: Option<Vec<f64>>,
        block: &[&str],
        neighbors: &[&str],
        ancestors: &[&str],
    ) -> ReconciliationItem {
        let interval = TemporalInterval::new(Some(10), Some(20))
            .unwrap_or_else(|error| unreachable!("valid interval failed: {error}"));
        ReconciliationItem::new(
            item_id.to_owned(),
            content_hash.map(str::to_owned),
            embedding,
            interval,
            block.iter().map(|value| (*value).to_owned()).collect(),
            neighbors.iter().map(|value| (*value).to_owned()).collect(),
            ancestors.iter().map(|value| (*value).to_owned()).collect(),
        )
        .unwrap_or_else(|error| unreachable!("valid item failed: {error}"))
    }

    fn policy(max_block_size: usize, max_candidates_per_item: usize) -> CandidatePolicy {
        CandidatePolicy::new(0.8, 0.5, max_block_size, max_candidates_per_item)
            .unwrap_or_else(|error| unreachable!("valid policy failed: {error}"))
    }

    #[test]
    fn exact_duplicates_use_a_linear_representative_expansion() {
        let result = discover_candidates(
            &[
                item("c", Some("same"), None, &[], &[], &[]),
                item("b", Some("same"), None, &[], &[], &[]),
                item("a", Some("same"), None, &[], &[], &[]),
            ],
            policy(8, 8),
        )
        .unwrap_or_else(|error| unreachable!("candidate discovery failed: {error}"));
        assert_eq!(result.exact_duplicate_groups.len(), 1);
        assert_eq!(result.exact_duplicate_groups[0].item_ids, ["a", "b", "c"]);
        assert_eq!(result.metrics.comparison_pairs, 2);
        assert_eq!(result.candidate_pairs.len(), 2);
        assert_eq!(result.candidate_pairs[0].left_id, "a");
        assert_eq!(result.candidate_pairs[0].right_id, "b");
        assert_eq!(result.candidate_pairs[1].left_id, "a");
        assert_eq!(result.candidate_pairs[1].right_id, "c");
    }

    #[test]
    fn hard_negative_in_the_same_block_is_not_returned_without_evidence() {
        let result = discover_candidates(
            &[
                item("a", None, Some(vec![1.0, 0.0]), &["topic"], &[], &[]),
                item("b", None, Some(vec![0.0, 1.0]), &["topic"], &[], &[]),
            ],
            policy(8, 8),
        )
        .unwrap_or_else(|error| unreachable!("candidate discovery failed: {error}"));
        assert_eq!(result.metrics.comparison_pairs, 1);
        assert!(result.candidate_pairs.is_empty());
    }

    #[test]
    fn vector_graph_temporal_and_lineage_evidence_remain_separate_from_policy() {
        let result = discover_candidates(
            &[
                item(
                    "old",
                    None,
                    Some(vec![1.0, 0.0]),
                    &["topic"],
                    &["shared", "x"],
                    &[],
                ),
                item(
                    "new",
                    None,
                    Some(vec![0.99, 0.01]),
                    &["topic"],
                    &["shared", "y"],
                    &["old"],
                ),
            ],
            policy(8, 8),
        )
        .unwrap_or_else(|error| unreachable!("candidate discovery failed: {error}"));
        let pair = &result.candidate_pairs[0];
        assert!(pair.vector_similarity.is_some_and(|score| score > 0.99));
        assert!(pair.temporal_overlap);
        assert!((pair.graph_similarity - (1.0 / 3.0)).abs() < f64::EPSILON);
        assert_eq!(pair.lineage, LineageEvidence::LeftDescendsFromRight);
    }

    #[test]
    fn oversized_blocks_fail_closed_before_quadratic_expansion() {
        let result = discover_candidates(
            &[
                item("a", None, None, &["wide"], &[], &[]),
                item("b", None, None, &["wide"], &[], &[]),
                item("c", None, None, &["wide"], &[], &[]),
            ],
            policy(2, 8),
        );
        assert!(result.is_err());
    }

    #[test]
    fn per_item_caps_are_deterministic() {
        let result = discover_candidates(
            &[
                item("a", None, Some(vec![1.0, 0.0]), &["all"], &[], &[]),
                item("b", None, Some(vec![1.0, 0.0]), &["all"], &[], &[]),
                item("c", None, Some(vec![1.0, 0.0]), &["all"], &[], &[]),
            ],
            policy(8, 1),
        )
        .unwrap_or_else(|error| unreachable!("candidate discovery failed: {error}"));
        assert_eq!(result.candidate_pairs.len(), 1);
        assert_eq!(result.candidate_pairs[0].left_id, "a");
        assert_eq!(result.candidate_pairs[0].right_id, "b");
    }
}
