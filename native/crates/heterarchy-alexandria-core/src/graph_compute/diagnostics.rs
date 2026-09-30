//! Deterministic graph orphan census and relation suggestion compute.

use std::collections::{BTreeMap, BTreeSet};

use serde::Serialize;

use super::{GraphComputeError, GraphSourceEdge, GraphSourceNote};

const MAX_DIAGNOSTIC_NOTES: usize = 2_000_000;
const MAX_DIAGNOSTIC_EDGES: usize = 8_000_000;
const MAX_DIAGNOSTIC_LIMIT: usize = 200;
const MAX_SUGGESTION_LIMIT: usize = 50;

/// One bounded orphan census request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphOrphanCensusRequest {
    /// Optional project scope.
    pub project: Option<String>,
    /// Stable relative-path cursor from the previous page.
    pub cursor: Option<String>,
    /// Maximum records to return.
    pub limit: usize,
}

/// One bounded relation-suggestion request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphRelationSuggestionRequest {
    /// Canonical seed note identity.
    pub seed_note_id: String,
    /// Maximum suggestions to return.
    pub limit: usize,
}

/// Complete graph diagnostic input over already-read source rows.
#[derive(Debug, Clone, PartialEq)]
pub struct GraphDiagnosticsRequest {
    /// Healthy projection nodes with typed metadata.
    pub notes: Vec<GraphSourceNote>,
    /// Healthy projection edges.
    pub edges: Vec<GraphSourceEdge>,
    /// Tags keyed by canonical note identity.
    pub tags: BTreeMap<String, Vec<String>>,
    /// Optional orphan census page request.
    pub orphan_census: Option<GraphOrphanCensusRequest>,
    /// Optional relation suggestion request.
    pub relation_suggestions: Option<GraphRelationSuggestionRequest>,
}

/// One deterministic orphan debt record.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphOrphanRecord {
    /// Canonical note identity.
    pub note_id: String,
    /// Canonical note path.
    pub relative_path: String,
    /// Current note title.
    pub title: String,
    /// Optional project identity.
    pub project: Option<String>,
    /// Total incoming resolved projected edges.
    pub in_degree: usize,
    /// Total outgoing resolved projected edges.
    pub out_degree: usize,
    /// Incoming `contains` ownership edges.
    pub canonical_parent_count: usize,
    /// Whether wikilink connectivity exists without canonical ownership.
    pub has_wikilink_connectivity: bool,
    /// Debt classes for this record.
    pub debt_kinds: Vec<String>,
}

/// One deterministic relation suggestion with evidence.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GraphRelationSuggestion {
    /// Canonical candidate note identity.
    pub candidate_note_id: String,
    /// Canonical candidate path.
    pub candidate_path: String,
    /// Canonical candidate title.
    pub candidate_title: String,
    /// Suggestion relation kind.
    pub relation: String,
    /// Bounded deterministic confidence.
    pub confidence: f64,
    /// Tags shared with the seed.
    pub shared_tags: Vec<String>,
    /// Number of shared one-hop neighbors.
    pub shared_neighbor_count: usize,
    /// Lowercase title tokens shared with the seed.
    pub title_overlap_tokens: Vec<String>,
    /// Human-readable deterministic evidence.
    pub explanation: String,
}

/// Complete deterministic graph diagnostic output.
#[derive(Debug, Clone, PartialEq, Serialize, Default)]
pub struct GraphDiagnosticsResult {
    /// Number of the shared Python/Rust contract.
    pub contract_version: u16,
    /// Graph diagnostic algorithm version.
    pub graph_compute_version: u16,
    /// Bounded orphan page.
    pub orphans: Vec<GraphOrphanRecord>,
    /// Total orphan debt after project filtering.
    pub total_orphans: usize,
    /// Cursor for the next stable path page.
    pub next_cursor: Option<String>,
    /// Bounded relation suggestions.
    pub suggestions: Vec<GraphRelationSuggestion>,
}

/// Compute orphan debt and relation suggestions without persistence effects.
///
/// # Errors
///
/// Returns an error when the bounded diagnostic request exceeds the accepted
/// input or page limits.
pub fn compute_graph_diagnostics(
    request: GraphDiagnosticsRequest,
    contract_version: u16,
    graph_compute_version: u16,
) -> Result<GraphDiagnosticsResult, GraphComputeError> {
    validate_request(&request)?;
    let mut nodes = request.notes;
    nodes.sort_by(|left, right| left.relative_path.cmp(&right.relative_path));
    nodes.dedup_by(|right, left| right.note_id == left.note_id);
    let mut edges = request.edges;
    edges.sort_by(|left, right| left.edge_id.cmp(&right.edge_id));
    edges.dedup_by(|right, left| right.edge_id == left.edge_id);

    let node_ids = nodes
        .iter()
        .map(|node| node.note_id.as_str().to_owned())
        .collect::<BTreeSet<_>>();
    let mut incoming: BTreeMap<String, usize> = BTreeMap::new();
    let mut outgoing: BTreeMap<String, usize> = BTreeMap::new();
    let mut canonical_parents: BTreeMap<String, usize> = BTreeMap::new();
    let mut neighbors: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let mut wikilink_connectivity = BTreeSet::new();
    for edge in &edges {
        let Some(target) = edge.target_note_id.as_deref() else {
            continue;
        };
        if !node_ids.contains(edge.source_note_id.as_str()) || !node_ids.contains(target) {
            continue;
        }
        *outgoing.entry(edge.source_note_id.clone()).or_default() += 1;
        *incoming.entry(target.to_owned()).or_default() += 1;
        neighbors
            .entry(edge.source_note_id.clone())
            .or_default()
            .insert(target.to_owned());
        neighbors
            .entry(target.to_owned())
            .or_default()
            .insert(edge.source_note_id.clone());
        if edge.relation == "contains" {
            *canonical_parents.entry(target.to_owned()).or_default() += 1;
        }
        if edge.relation == "wikilink" || edge.source_kind == "wikilink" {
            wikilink_connectivity.insert(edge.source_note_id.clone());
            wikilink_connectivity.insert(target.to_owned());
        }
    }

    let project = request
        .orphan_census
        .as_ref()
        .and_then(|item| item.project.as_deref());
    let mut debt = nodes
        .iter()
        .filter(|node| project.is_none() || node.project.as_deref() == project)
        .filter_map(|node| {
            let in_degree = incoming.get(node.note_id.as_str()).copied().unwrap_or(0);
            let out_degree = outgoing.get(node.note_id.as_str()).copied().unwrap_or(0);
            let parent_count = canonical_parents
                .get(node.note_id.as_str())
                .copied()
                .unwrap_or(0);
            let mut debt_kinds = Vec::new();
            if in_degree == 0 && out_degree == 0 {
                debt_kinds.push("degree_zero".to_owned());
            }
            if parent_count == 0 {
                debt_kinds.push("missing_canonical_parent".to_owned());
            }
            if debt_kinds.is_empty() {
                return None;
            }
            Some(GraphOrphanRecord {
                note_id: node.note_id.as_str().to_owned(),
                relative_path: node.relative_path.as_str().to_owned(),
                title: node.title.clone(),
                project: node.project.clone(),
                in_degree,
                out_degree,
                canonical_parent_count: parent_count,
                has_wikilink_connectivity: wikilink_connectivity.contains(node.note_id.as_str()),
                debt_kinds,
            })
        })
        .collect::<Vec<_>>();
    debt.sort_by(|left, right| left.relative_path.cmp(&right.relative_path));
    let total_orphans = debt.len();
    let (orphans, next_cursor) = page_orphans(&debt, request.orphan_census.as_ref());

    let suggestions = request
        .relation_suggestions
        .as_ref()
        .map(|suggestion| relation_suggestions(&nodes, &request.tags, &neighbors, suggestion))
        .unwrap_or_default();
    Ok(GraphDiagnosticsResult {
        contract_version,
        graph_compute_version,
        orphans,
        total_orphans,
        next_cursor,
        suggestions,
    })
}

fn validate_request(request: &GraphDiagnosticsRequest) -> Result<(), GraphComputeError> {
    if request.notes.len() > MAX_DIAGNOSTIC_NOTES {
        return Err(GraphComputeError::new(
            "diagnostic note count exceeds limit",
        ));
    }
    if request.edges.len() > MAX_DIAGNOSTIC_EDGES {
        return Err(GraphComputeError::new(
            "diagnostic edge count exceeds limit",
        ));
    }
    if let Some(census) = &request.orphan_census
        && (census.limit == 0 || census.limit > MAX_DIAGNOSTIC_LIMIT)
    {
        return Err(GraphComputeError::new("orphan limit exceeds bound"));
    }
    if let Some(suggestions) = &request.relation_suggestions
        && (suggestions.seed_note_id.trim().is_empty()
            || suggestions.limit == 0
            || suggestions.limit > MAX_SUGGESTION_LIMIT)
    {
        return Err(GraphComputeError::new("invalid suggestion request"));
    }
    Ok(())
}

fn page_orphans(
    records: &[GraphOrphanRecord],
    request: Option<&GraphOrphanCensusRequest>,
) -> (Vec<GraphOrphanRecord>, Option<String>) {
    let Some(request) = request else {
        return (Vec::new(), None);
    };
    let start = request.cursor.as_deref().map_or(0, |cursor| {
        records
            .iter()
            .position(|record| record.relative_path.as_str() > cursor)
            .unwrap_or(records.len())
    });
    let end = start.saturating_add(request.limit).min(records.len());
    let page = records[start..end].to_vec();
    let next = if end < records.len() {
        page.last().map(|record| record.relative_path.clone())
    } else {
        None
    };
    (page, next)
}

fn relation_suggestions(
    notes: &[GraphSourceNote],
    tags: &BTreeMap<String, Vec<String>>,
    neighbors: &BTreeMap<String, BTreeSet<String>>,
    request: &GraphRelationSuggestionRequest,
) -> Vec<GraphRelationSuggestion> {
    let Some(seed) = notes
        .iter()
        .find(|note| note.note_id.as_str() == request.seed_note_id)
    else {
        return Vec::new();
    };
    let seed_tags = normalized_tags(tags.get(seed.note_id.as_str()));
    let seed_tokens = title_tokens(seed.title.as_str());
    let seed_neighbors = neighbors
        .get(seed.note_id.as_str())
        .cloned()
        .unwrap_or_default();
    let mut suggestions = notes
        .iter()
        .filter(|candidate| candidate.note_id != seed.note_id)
        .filter(|candidate| seed.project.is_none() || candidate.project == seed.project)
        .filter_map(|candidate| {
            let shared_tags = seed_tags
                .intersection(&normalized_tags(tags.get(candidate.note_id.as_str())))
                .cloned()
                .collect::<Vec<_>>();
            let title_overlap_tokens = seed_tokens
                .intersection(&title_tokens(candidate.title.as_str()))
                .cloned()
                .collect::<Vec<_>>();
            let shared_neighbor_count = seed_neighbors
                .intersection(
                    &neighbors
                        .get(candidate.note_id.as_str())
                        .cloned()
                        .unwrap_or_default(),
                )
                .count();
            let score = 2 * shared_tags.len()
                + title_overlap_tokens.len()
                + 3 * shared_neighbor_count.min(2);
            if score == 0 {
                return None;
            }
            let mut evidence = Vec::new();
            if !shared_tags.is_empty() {
                evidence.push(format!("shared tags: {}", shared_tags.join(", ")));
            }
            if !title_overlap_tokens.is_empty() {
                evidence.push(format!(
                    "title overlap: {}",
                    title_overlap_tokens.join(", ")
                ));
            }
            if shared_neighbor_count > 0 {
                evidence.push(format!("shared neighbors: {shared_neighbor_count}"));
            }
            Some(GraphRelationSuggestion {
                candidate_note_id: candidate.note_id.as_str().to_owned(),
                candidate_path: candidate.relative_path.as_str().to_owned(),
                candidate_title: candidate.title.clone(),
                relation: "related".to_owned(),
                confidence: match score {
                    0 => 0.0,
                    1 => 0.167,
                    2 => 0.333,
                    3 => 0.5,
                    4 => 0.667,
                    5 => 0.833,
                    _ => 1.0,
                },
                shared_tags,
                shared_neighbor_count,
                title_overlap_tokens,
                explanation: evidence.join("; "),
            })
        })
        .collect::<Vec<_>>();
    suggestions.sort_by(|left, right| {
        right
            .confidence
            .total_cmp(&left.confidence)
            .then_with(|| left.candidate_path.cmp(&right.candidate_path))
    });
    suggestions.truncate(request.limit);
    suggestions
}

fn normalized_tags(tags: Option<&Vec<String>>) -> BTreeSet<String> {
    tags.into_iter()
        .flatten()
        .map(|tag| tag.trim().to_lowercase())
        .filter(|tag| !tag.is_empty())
        .collect()
}

fn title_tokens(title: &str) -> BTreeSet<String> {
    title
        .split_whitespace()
        .map(str::to_lowercase)
        .filter(|token| token.chars().count() > 1)
        .collect()
}
