//! Deterministic graph projection, diff, and bounded algorithm compute.

mod algorithms;
mod candidate_selection;
mod projection;

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt::{Display, Formatter};

use serde::Serialize;

use crate::ComputeContractVersion;
use crate::document_analysis::{DocumentId, RelativeVaultPath};

/// Version of the graph compute schema and deterministic algorithms.
pub const GRAPH_COMPUTE_VERSION: u16 = 1;

const MAX_SOURCE_NOTES: usize = 2_000_000;
const MAX_SOURCE_EDGES: usize = 8_000_000;
const MAX_REQUESTS: usize = 100_000;
const MAX_BATCH_SIZE: usize = 1_000_000;
const MAX_TRAVERSAL_DEPTH: usize = 1_024;
const MAX_TRAVERSAL_RESULTS: usize = 1_000_000;
const MAX_SELECTED_GRAPH_CANDIDATES: usize = 1_024;

/// Current relational-index status supplied by the Python effect boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphIndexStatus {
    /// Healthy indexed source row eligible for projection.
    Indexed,
    /// Source row is stale and excluded from the current projection.
    Stale,
    /// Source row failed indexing and emits a projection issue.
    Error,
}

/// One source note loaded by Python from the current relational index.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphSourceNote {
    /// Stable note identity.
    pub note_id: DocumentId,
    /// Vault-relative note path.
    pub relative_path: RelativeVaultPath,
    /// Alexandria note type string validated by Python.
    pub alexandria_type: String,
    /// Current display title.
    pub title: String,
    /// Current lifecycle status.
    pub status: String,
    /// Optional project identity.
    pub project: Option<String>,
    /// Explicit aliases already decoded from typed frontmatter.
    pub aliases: Vec<String>,
    /// Relational-index status.
    pub index_status: GraphIndexStatus,
}

/// One indexed graph edge loaded by Python without moving persistence authority.
#[derive(Debug, Clone, PartialEq)]
pub struct GraphSourceEdge {
    /// Stable edge identity.
    pub edge_id: String,
    /// Source note identity.
    pub source_note_id: String,
    /// Source path recorded by the current edge row.
    pub source_path: String,
    /// Optional already-resolved target identity.
    pub target_note_id: Option<String>,
    /// Target path or unresolved link name.
    pub target_path: String,
    /// Relation string validated by Python.
    pub relation: String,
    /// Current edge confidence.
    pub confidence: f64,
    /// Edge provenance string validated by Python.
    pub source_kind: String,
}

/// Projected healthy graph node.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphProjectionNode {
    /// Stable note identity.
    pub note_id: String,
    /// Canonical healthy source path.
    pub relative_path: String,
    /// Alexandria note type.
    pub alexandria_type: String,
    /// Display title.
    pub title: String,
    /// Lifecycle status.
    pub status: String,
    /// Optional project identity.
    pub project: Option<String>,
}

/// Projected edge whose endpoints both resolve to healthy nodes.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GraphProjectionEdge {
    /// Stable edge identity.
    pub edge_id: String,
    /// Resolved source note identity.
    pub source_note_id: String,
    /// Canonical source path.
    pub source_path: String,
    /// Resolved target note identity.
    pub target_note_id: String,
    /// Canonical target path.
    pub target_path: String,
    /// Relation string.
    pub relation: String,
    /// Current confidence.
    pub confidence: f64,
    /// Current provenance string.
    pub source_kind: String,
}

/// One immutable projected graph snapshot.
#[derive(Debug, Clone, PartialEq, Serialize, Default)]
pub struct GraphProjection {
    /// Nodes ordered by stable note identity.
    pub nodes: Vec<GraphProjectionNode>,
    /// Edges ordered by stable edge identity.
    pub edges: Vec<GraphProjectionEdge>,
}

/// Current non-fatal projection issue code.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphProjectionIssueCode {
    /// Source note has an index error.
    IndexError,
    /// Edge target is absent from the healthy source set.
    MissingTargetNote,
    /// Edge link name resolves to multiple healthy notes.
    AmbiguousTargetNote,
}

impl GraphProjectionIssueCode {
    const fn as_str(self) -> &'static str {
        match self {
            Self::IndexError => "index_error",
            Self::MissingTargetNote => "missing_target_note",
            Self::AmbiguousTargetNote => "ambiguous_target_note",
        }
    }
}

/// One non-fatal issue from pure projection planning.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphProjectionIssue {
    /// Stable issue code.
    pub code: GraphProjectionIssueCode,
    /// Relevant path.
    pub relative_path: String,
    /// Optional note identity.
    pub note_id: Option<String>,
    /// Optional edge identity.
    pub edge_id: Option<String>,
    /// Compatibility-preserving detail.
    pub detail: String,
}

/// Current source-builder counts.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct GraphProjectionMetrics {
    /// Notes plus edges inspected.
    pub scanned: usize,
    /// Projected nodes plus edges.
    pub indexed: usize,
    /// Reserved update count; current full rebuilds report zero.
    pub updated: usize,
    /// Inputs not present in the projected graph.
    pub skipped: usize,
    /// Non-fatal issue count.
    pub errors: usize,
}

/// One bounded projection batch matching current Python slicing semantics.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GraphProjectionBatch {
    /// Zero-based batch sequence.
    pub batch_index: usize,
    /// Bounded node/edge slices for this sequence.
    pub projection: GraphProjection,
}

/// Duplicate or ambiguous structural inputs surfaced by the Rust candidate.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Default)]
pub struct GraphStructuralDiagnostics {
    /// Repeated source note identities, sorted and deduplicated.
    pub duplicate_note_ids: Vec<String>,
    /// Repeated source edge identities, sorted and deduplicated.
    pub duplicate_edge_ids: Vec<String>,
    /// Case-folded link names mapping to multiple healthy note paths.
    pub ambiguous_link_names: Vec<AmbiguousLinkName>,
}

/// One ambiguous case-folded link name and its candidate paths.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AmbiguousLinkName {
    /// Python-compatible full Unicode case-folded name.
    pub normalized_name: String,
    /// Candidate paths ordered lexicographically.
    pub candidate_paths: Vec<String>,
}

/// Direction for one bounded traversal request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TraversalDirection {
    /// Follow source to target.
    Outgoing,
    /// Follow target to source.
    Incoming,
    /// Traverse either direction.
    Both,
}

/// One explicit bounded traversal query over the computed projection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphTraversalRequest {
    /// Caller-owned correlation identity.
    pub request_id: String,
    /// Starting note identity.
    pub start_note_id: String,
    /// Direction to traverse.
    pub direction: TraversalDirection,
    /// Optional relation allow-list; empty means all relations.
    pub relations: Vec<String>,
    /// Maximum number of edge hops.
    pub max_depth: usize,
    /// Maximum returned nodes including the start node.
    pub max_results: usize,
}

impl GraphTraversalRequest {
    /// Validate one bounded traversal request.
    ///
    /// # Errors
    ///
    /// Returns an error when identifiers are blank or bounds exceed the native contract.
    pub fn validate(&self) -> Result<(), GraphComputeError> {
        validate_non_blank("traversal request_id", &self.request_id)?;
        validate_non_blank("traversal start_note_id", &self.start_note_id)?;
        validate_bounds(self.max_depth, self.max_results)
    }
}

/// One explicit supersedes-lineage query.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphLineageRequest {
    /// Caller-owned correlation identity.
    pub request_id: String,
    /// Note whose lineage should be expanded.
    pub note_id: String,
    /// Maximum number of supersedes hops.
    pub max_depth: usize,
    /// Maximum returned nodes in each direction including no duplicate start.
    pub max_results: usize,
}

impl GraphLineageRequest {
    /// Validate one bounded lineage request.
    ///
    /// # Errors
    ///
    /// Returns an error when identifiers are blank or bounds exceed the native contract.
    pub fn validate(&self) -> Result<(), GraphComputeError> {
        validate_non_blank("lineage request_id", &self.request_id)?;
        validate_non_blank("lineage note_id", &self.note_id)?;
        validate_bounds(self.max_depth, self.max_results)
    }
}

fn validate_bounds(max_depth: usize, max_results: usize) -> Result<(), GraphComputeError> {
    if max_depth > MAX_TRAVERSAL_DEPTH {
        return Err(GraphComputeError::new(format!(
            "max_depth exceeds the {MAX_TRAVERSAL_DEPTH} hop limit"
        )));
    }
    if max_results == 0 || max_results > MAX_TRAVERSAL_RESULTS {
        return Err(GraphComputeError::new(format!(
            "max_results must be between 1 and {MAX_TRAVERSAL_RESULTS}"
        )));
    }
    Ok(())
}

/// Complete coarse-grained graph compute input.
#[derive(Debug, Clone, PartialEq)]
pub struct GraphComputeRequest {
    source_notes: Vec<GraphSourceNote>,
    source_edges: Vec<GraphSourceEdge>,
    previous_projection: Option<GraphProjection>,
    batch_size: usize,
    traversal_requests: Vec<GraphTraversalRequest>,
    lineage_requests: Vec<GraphLineageRequest>,
}

impl GraphComputeRequest {
    /// Construct and validate one bounded graph compute request.
    ///
    /// # Errors
    ///
    /// Returns an error when source cardinality, batch size, identifiers, or query bounds are invalid.
    pub fn new(
        source_notes: Vec<GraphSourceNote>,
        source_edges: Vec<GraphSourceEdge>,
        previous_projection: Option<GraphProjection>,
        batch_size: usize,
        traversal_requests: Vec<GraphTraversalRequest>,
        lineage_requests: Vec<GraphLineageRequest>,
    ) -> Result<Self, GraphComputeError> {
        if source_notes.len() > MAX_SOURCE_NOTES {
            return Err(GraphComputeError::new(format!(
                "source note count exceeds the {MAX_SOURCE_NOTES} item limit"
            )));
        }
        if source_edges.len() > MAX_SOURCE_EDGES {
            return Err(GraphComputeError::new(format!(
                "source edge count exceeds the {MAX_SOURCE_EDGES} item limit"
            )));
        }
        if batch_size == 0 || batch_size > MAX_BATCH_SIZE {
            return Err(GraphComputeError::new(format!(
                "batch_size must be between 1 and {MAX_BATCH_SIZE}"
            )));
        }
        if traversal_requests
            .len()
            .saturating_add(lineage_requests.len())
            > MAX_REQUESTS
        {
            return Err(GraphComputeError::new(format!(
                "graph request count exceeds the {MAX_REQUESTS} item limit"
            )));
        }
        validate_source(&source_notes, &source_edges)?;
        for request in &traversal_requests {
            request.validate()?;
        }
        for request in &lineage_requests {
            request.validate()?;
        }
        Ok(Self {
            source_notes,
            source_edges,
            previous_projection,
            batch_size,
            traversal_requests,
            lineage_requests,
        })
    }
}

fn validate_source(
    notes: &[GraphSourceNote],
    edges: &[GraphSourceEdge],
) -> Result<(), GraphComputeError> {
    for note in notes {
        validate_non_blank("note_id", note.note_id.as_str())?;
        validate_non_blank("relative_path", note.relative_path.as_str())?;
    }
    for edge in edges {
        for (name, value) in [
            ("edge_id", edge.edge_id.as_str()),
            ("source_note_id", edge.source_note_id.as_str()),
            ("target_path", edge.target_path.as_str()),
            ("relation", edge.relation.as_str()),
            ("source_kind", edge.source_kind.as_str()),
        ] {
            validate_non_blank(name, value)?;
        }
        if !edge.confidence.is_finite() {
            return Err(GraphComputeError::new(format!(
                "edge {} confidence must be finite",
                edge.edge_id
            )));
        }
    }
    Ok(())
}

fn validate_non_blank(name: &str, value: &str) -> Result<(), GraphComputeError> {
    if value.trim().is_empty() {
        return Err(GraphComputeError::new(format!("{name} must not be blank")));
    }
    Ok(())
}

/// Invalid input or an impossible graph-compute invariant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphComputeError {
    message: String,
}

impl GraphComputeError {
    pub(crate) fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for GraphComputeError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for GraphComputeError {}

/// Stable adjacency for one projected node.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphAdjacency {
    /// Node identity.
    pub note_id: String,
    /// Outgoing neighbors ordered by note identity.
    pub outgoing: Vec<String>,
    /// Incoming neighbors ordered by note identity.
    pub incoming: Vec<String>,
}

/// One strongly connected component representing a directed cycle.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphCycleComponent {
    /// Component node identities in lexical order.
    pub note_ids: Vec<String>,
    /// Whether the component is a one-node self-loop.
    pub self_loop: bool,
}

/// One node discovered by bounded breadth-first traversal.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphTraversalVisit {
    /// Node identity.
    pub note_id: String,
    /// Minimum hop distance from the start node.
    pub depth: usize,
}

/// Result for one bounded traversal request.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphTraversalResult {
    /// Caller-owned correlation identity.
    pub request_id: String,
    /// Starting note identity.
    pub start_note_id: String,
    /// Whether the start node existed in the projected graph.
    pub start_found: bool,
    /// Stable breadth-first visits including the start node when found.
    pub visits: Vec<GraphTraversalVisit>,
    /// Whether depth or result bounds prevented full expansion.
    pub truncated: bool,
}

/// One Rust-owned shortest-path hop supporting a selected retrieval candidate.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphCandidatePathHop {
    /// Stable projected edge identity used for this hop.
    pub edge_id: String,
    /// Traversal predecessor note identity.
    pub source_note_id: String,
    /// Note identity reached by this hop.
    pub target_note_id: String,
    /// Projected relation followed by this hop.
    pub relation: String,
    /// Actual traversal direction relative to the predecessor note.
    pub direction: TraversalDirection,
    /// Cumulative hop distance from the selected seed after this edge.
    pub depth: usize,
}

/// One bounded graph candidate selected from traversal evidence.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphSelectedCandidate {
    /// Selected projected note identity.
    pub note_id: String,
    /// Minimum traversal distance from any seed.
    pub min_depth: usize,
    /// Number of seed traversals that reached this note.
    pub seed_support: usize,
    /// Shared normalized character trigrams between query and projected title.
    pub shared_title_trigrams: usize,
    /// Union size used for deterministic title-trigram similarity ordering.
    pub title_trigram_union: usize,
    /// Rust-owned shortest path from the deterministic selected seed to this candidate.
    pub path_hops: Vec<GraphCandidatePathHop>,
}

/// Query/title relevance evidence for one caller-supplied projected note.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphTitleRelevance {
    /// Projected note identity.
    pub note_id: String,
    /// Shared normalized character trigrams between query and projected title.
    pub shared_title_trigrams: usize,
    /// Union size used for deterministic title-trigram similarity comparison.
    pub title_trigram_union: usize,
}

/// Traversal trace plus bounded relevance-selected graph candidates.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphCandidateSelection {
    /// Underlying deterministic traversal results used for candidate discovery.
    pub traversals: Vec<GraphTraversalResult>,
    /// Selected candidates ordered by title relevance, graph distance, and support.
    pub candidates: Vec<GraphSelectedCandidate>,
    /// Title-relevance evidence for caller-supplied primary note identities.
    pub primary_title_relevance: Vec<GraphTitleRelevance>,
}

/// Supersedes ancestry and descendants for one requested note.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphLineageResult {
    /// Caller-owned correlation identity.
    pub request_id: String,
    /// Requested note identity.
    pub note_id: String,
    /// Whether the requested note existed.
    pub note_found: bool,
    /// Nodes reached by following outgoing `supersedes` edges.
    pub supersedes: Vec<GraphTraversalVisit>,
    /// Nodes reached by following incoming `supersedes` edges.
    pub superseded_by: Vec<GraphTraversalVisit>,
    /// Whether either direction was truncated.
    pub truncated: bool,
}

/// Identity-level projection changes; Python remains authority for applying them.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Default)]
pub struct GraphProjectionDiff {
    /// Node identities absent from the previous snapshot.
    pub added_node_ids: Vec<String>,
    /// Node identities absent from the current snapshot.
    pub removed_node_ids: Vec<String>,
    /// Node identities whose projected payload changed.
    pub updated_node_ids: Vec<String>,
    /// Edge identities absent from the previous snapshot.
    pub added_edge_ids: Vec<String>,
    /// Edge identities absent from the current snapshot.
    pub removed_edge_ids: Vec<String>,
    /// Edge identities whose projected payload changed.
    pub updated_edge_ids: Vec<String>,
}

/// Pure graph analysis over the current projected snapshot.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Default)]
pub struct GraphAnalysis {
    /// Stable incoming/outgoing adjacency for every projected node.
    pub adjacency: Vec<GraphAdjacency>,
    /// Nodes with no incoming or outgoing projected edge.
    pub orphan_note_ids: Vec<String>,
    /// Directed strongly connected components that form cycles.
    pub cycles: Vec<GraphCycleComponent>,
    /// Requested bounded traversal results.
    pub traversals: Vec<GraphTraversalResult>,
    /// Requested supersedes lineage results.
    pub lineages: Vec<GraphLineageResult>,
    /// Diff against the optional previous projection.
    pub diff: GraphProjectionDiff,
}

/// Complete graph compute response.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GraphComputeResult {
    /// Python/Rust compute contract version.
    pub contract_version: u16,
    /// Graph compute schema and algorithm version.
    pub graph_compute_version: u16,
    /// Current healthy projection.
    pub projection: GraphProjection,
    /// Projection batches matching current Python slicing semantics.
    pub batches: Vec<GraphProjectionBatch>,
    /// Non-fatal current projection issues in stable order.
    pub issues: Vec<GraphProjectionIssue>,
    /// Current source-builder counts.
    pub metrics: GraphProjectionMetrics,
    /// Duplicate and ambiguous input diagnostics.
    pub structural_diagnostics: GraphStructuralDiagnostics,
    /// Pure graph analysis and diff plan.
    pub analysis: GraphAnalysis,
}

/// Execute bounded deterministic traversal over an already-built active projection.
///
/// This path intentionally skips projection construction, cycle analysis, orphan analysis, and
/// diff calculation so retrieval can reuse the Python-owned active graph snapshot without
/// rebuilding it for every search.
///
/// # Errors
///
/// Returns an error for excessive request counts, invalid traversal bounds, duplicate projected
/// node identities, or projected edges whose endpoints are missing.
pub fn traverse_projection(
    projection: &GraphProjection,
    traversal_requests: &[GraphTraversalRequest],
) -> Result<Vec<GraphTraversalResult>, GraphComputeError> {
    if traversal_requests.len() > MAX_REQUESTS {
        return Err(GraphComputeError::new(format!(
            "graph traversal request count exceeds the {MAX_REQUESTS} item limit"
        )));
    }
    for request in traversal_requests {
        request.validate()?;
    }
    algorithms::traverse_projection(projection, traversal_requests)
}

/// Traverse one active projection and select a small relevance-bounded graph candidate set.
///
/// Selection first ranks normalized query/title character-trigram overlap, then uses graph
/// distance, multi-seed support, and stable traversal order as deterministic tie-breakers.
/// Python remains authority for hydrating selected note identities and applying retrieval policy.
///
/// # Errors
///
/// Returns an error for blank queries, excessive request or candidate counts, invalid traversal
/// bounds, duplicate projected node identities, or projected edges whose endpoints are missing.
pub fn select_projection_candidates(
    projection: &GraphProjection,
    traversal_requests: &[GraphTraversalRequest],
    primary_note_ids: &[String],
    query: &str,
    max_candidates: usize,
    min_shared_trigrams: usize,
) -> Result<GraphCandidateSelection, GraphComputeError> {
    validate_non_blank("graph candidate query", query)?;
    if traversal_requests.len() > MAX_REQUESTS {
        return Err(GraphComputeError::new(format!(
            "graph traversal request count exceeds the {MAX_REQUESTS} item limit"
        )));
    }
    if primary_note_ids.len() > MAX_SELECTED_GRAPH_CANDIDATES {
        return Err(GraphComputeError::new(format!(
            "primary note count exceeds the {MAX_SELECTED_GRAPH_CANDIDATES} item limit"
        )));
    }
    if max_candidates == 0 || max_candidates > MAX_SELECTED_GRAPH_CANDIDATES {
        return Err(GraphComputeError::new(format!(
            "max_candidates must be between 1 and {MAX_SELECTED_GRAPH_CANDIDATES}"
        )));
    }
    if min_shared_trigrams == 0 {
        return Err(GraphComputeError::new(
            "min_shared_trigrams must be one or greater",
        ));
    }
    for request in traversal_requests {
        request.validate()?;
    }
    let traversals = algorithms::traverse_projection(projection, traversal_requests)?;
    candidate_selection::select_candidates(
        projection,
        traversals,
        traversal_requests,
        primary_note_ids,
        query,
        max_candidates,
        min_shared_trigrams,
    )
}

/// Build the healthy projection and execute bounded deterministic graph algorithms.
///
/// # Errors
///
/// Returns an error when source projection inputs violate graph invariants or when bounded graph
/// analysis cannot be completed for the validated request.
pub fn compute_graph(
    request: GraphComputeRequest,
) -> Result<GraphComputeResult, GraphComputeError> {
    let GraphComputeRequest {
        source_notes,
        source_edges,
        previous_projection,
        batch_size,
        traversal_requests,
        lineage_requests,
    } = request;
    let projection_result = projection::build_projection(source_notes, source_edges, batch_size);
    let analysis = algorithms::analyze_projection(
        &projection_result.projection,
        previous_projection.as_ref(),
        &traversal_requests,
        &lineage_requests,
    )?;
    Ok(GraphComputeResult {
        contract_version: ComputeContractVersion::CURRENT.value(),
        graph_compute_version: GRAPH_COMPUTE_VERSION,
        projection: projection_result.projection,
        batches: projection_result.batches,
        issues: projection_result.issues,
        metrics: projection_result.metrics,
        structural_diagnostics: projection_result.structural_diagnostics,
        analysis,
    })
}

pub(crate) fn relation_filter(values: &[String]) -> BTreeSet<&str> {
    values.iter().map(String::as_str).collect()
}

#[cfg(test)]
mod tests {
    use super::{
        GraphComputeRequest, GraphIndexStatus, GraphLineageRequest, GraphProjection,
        GraphProjectionEdge, GraphProjectionIssueCode, GraphProjectionNode, GraphSourceEdge,
        GraphSourceNote, GraphTraversalRequest, TraversalDirection, compute_graph,
        traverse_projection,
    };
    use crate::document_analysis::{DocumentId, RelativeVaultPath};
    use unicode_normalization::UnicodeNormalization;

    fn note(note_id: &str, path: &str, status: GraphIndexStatus) -> GraphSourceNote {
        let note_id = match DocumentId::new(note_id.to_owned()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid note id rejected: {error}"),
        };
        let relative_path = match RelativeVaultPath::new(path.to_owned()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid path rejected: {error}"),
        };
        GraphSourceNote {
            note_id,
            relative_path,
            alexandria_type: "context".to_owned(),
            title: path.to_owned(),
            status: "active".to_owned(),
            project: None,
            aliases: Vec::new(),
            index_status: status,
        }
    }

    fn edge(edge_id: &str, source: &str, target: &str, relation: &str) -> GraphSourceEdge {
        GraphSourceEdge {
            edge_id: edge_id.to_owned(),
            source_note_id: source.to_owned(),
            source_path: format!("Contexts/{source}.md"),
            target_note_id: Some(target.to_owned()),
            target_path: format!("Contexts/{target}.md"),
            relation: relation.to_owned(),
            confidence: 1.0,
            source_kind: "frontmatter".to_owned(),
        }
    }

    fn projection_node(note_id: &str) -> GraphProjectionNode {
        GraphProjectionNode {
            note_id: note_id.to_owned(),
            relative_path: format!("Contexts/{note_id}.md"),
            alexandria_type: "context".to_owned(),
            title: note_id.to_uppercase(),
            status: "active".to_owned(),
            project: None,
        }
    }

    fn projection_edge(
        edge_id: &str,
        source: &str,
        target: &str,
        relation: &str,
        source_kind: &str,
    ) -> GraphProjectionEdge {
        GraphProjectionEdge {
            edge_id: edge_id.to_owned(),
            source_note_id: source.to_owned(),
            source_path: format!("Contexts/{source}.md"),
            target_note_id: target.to_owned(),
            target_path: format!("Contexts/{target}.md"),
            relation: relation.to_owned(),
            confidence: 1.0,
            source_kind: source_kind.to_owned(),
        }
    }

    fn unresolved_edge(
        edge_id: &str,
        source: &str,
        target_path: &str,
        relation: &str,
    ) -> GraphSourceEdge {
        GraphSourceEdge {
            edge_id: edge_id.to_owned(),
            source_note_id: source.to_owned(),
            source_path: format!("Contexts/{source}.md"),
            target_note_id: None,
            target_path: target_path.to_owned(),
            relation: relation.to_owned(),
            confidence: 1.0,
            source_kind: "wikilink".to_owned(),
        }
    }

    #[test]
    fn computes_projection_cycles_orphans_traversal_lineage_and_diff() {
        let notes = vec![
            note("a", "Contexts/a.md", GraphIndexStatus::Indexed),
            note("b", "Contexts/b.md", GraphIndexStatus::Indexed),
            note("c", "Contexts/c.md", GraphIndexStatus::Indexed),
            note("orphan", "Contexts/orphan.md", GraphIndexStatus::Indexed),
        ];
        let edges = vec![
            edge("e1", "a", "b", "supersedes"),
            edge("e2", "b", "c", "supersedes"),
            edge("e3", "c", "a", "related"),
        ];
        let request = match GraphComputeRequest::new(
            notes,
            edges,
            Some(GraphProjection::default()),
            2,
            vec![GraphTraversalRequest {
                request_id: "impact-a".to_owned(),
                start_note_id: "a".to_owned(),
                direction: TraversalDirection::Outgoing,
                relations: Vec::new(),
                max_depth: 3,
                max_results: 10,
            }],
            vec![GraphLineageRequest {
                request_id: "lineage-b".to_owned(),
                note_id: "b".to_owned(),
                max_depth: 4,
                max_results: 10,
            }],
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid graph request rejected: {error}"),
        };
        let result = match compute_graph(request) {
            Ok(value) => value,
            Err(error) => unreachable!("graph compute failed: {error}"),
        };
        assert_eq!(result.projection.nodes.len(), 4);
        assert_eq!(result.batches.len(), 2);
        assert_eq!(result.analysis.orphan_note_ids, vec!["orphan"]);
        assert_eq!(result.analysis.cycles.len(), 1);
        assert_eq!(result.analysis.cycles[0].note_ids, vec!["a", "b", "c"]);
        assert_eq!(result.analysis.traversals[0].visits.len(), 3);
        assert_eq!(
            result.analysis.lineages[0]
                .supersedes
                .iter()
                .map(|visit| visit.note_id.as_str())
                .collect::<Vec<_>>(),
            vec!["c"]
        );
        assert_eq!(
            result.analysis.lineages[0]
                .superseded_by
                .iter()
                .map(|visit| visit.note_id.as_str())
                .collect::<Vec<_>>(),
            vec!["a"]
        );
        assert_eq!(result.analysis.diff.added_node_ids.len(), 4);
        assert_eq!(result.analysis.diff.added_edge_ids.len(), 3);
    }

    #[test]
    fn traverses_active_projection_without_rebuilding_and_respects_depth_relation_and_cycles() {
        let projection = GraphProjection {
            nodes: vec![
                projection_node("a"),
                projection_node("b"),
                projection_node("c"),
            ],
            edges: vec![
                projection_edge("e1", "a", "b", "wikilink", "wikilink"),
                projection_edge("e2", "b", "c", "wikilink", "wikilink"),
                projection_edge("e3", "c", "a", "related", "frontmatter"),
            ],
        };
        let requests = vec![
            GraphTraversalRequest {
                request_id: "depth-one".to_owned(),
                start_note_id: "a".to_owned(),
                direction: TraversalDirection::Outgoing,
                relations: vec!["wikilink".to_owned()],
                max_depth: 1,
                max_results: 10,
            },
            GraphTraversalRequest {
                request_id: "depth-two".to_owned(),
                start_note_id: "a".to_owned(),
                direction: TraversalDirection::Outgoing,
                relations: vec!["wikilink".to_owned()],
                max_depth: 2,
                max_results: 10,
            },
            GraphTraversalRequest {
                request_id: "cycle-safe".to_owned(),
                start_note_id: "a".to_owned(),
                direction: TraversalDirection::Outgoing,
                relations: Vec::new(),
                max_depth: 8,
                max_results: 10,
            },
        ];

        let results = match traverse_projection(&projection, &requests) {
            Ok(value) => value,
            Err(error) => unreachable!("valid active projection traversal failed: {error}"),
        };

        assert_eq!(
            results[0]
                .visits
                .iter()
                .map(|visit| (visit.note_id.as_str(), visit.depth))
                .collect::<Vec<_>>(),
            vec![("a", 0), ("b", 1)]
        );
        assert!(results[0].truncated);
        assert_eq!(
            results[1]
                .visits
                .iter()
                .map(|visit| (visit.note_id.as_str(), visit.depth))
                .collect::<Vec<_>>(),
            vec![("a", 0), ("b", 1), ("c", 2)]
        );
        assert!(!results[1].truncated);
        assert_eq!(results[2].visits.len(), 3);
        assert!(!results[2].truncated);
    }

    #[test]
    fn resolves_nfc_and_nfd_equivalent_paths_without_changing_case_semantics() {
        let nfd_path = "Contexts/기능/Café.md".nfd().collect::<String>();
        let notes = vec![
            note("source", "Contexts/source.md", GraphIndexStatus::Indexed),
            note("target", &nfd_path, GraphIndexStatus::Indexed),
        ];
        let edges = vec![unresolved_edge(
            "unicode-edge",
            "source",
            "Contexts/기능/Café.md",
            "related",
        )];
        let request = match GraphComputeRequest::new(notes, edges, None, 10, Vec::new(), Vec::new())
        {
            Ok(value) => value,
            Err(error) => unreachable!("valid graph request rejected: {error}"),
        };
        let result = match compute_graph(request) {
            Ok(value) => value,
            Err(error) => unreachable!("graph compute failed: {error}"),
        };

        assert!(result.issues.is_empty());
        assert_eq!(result.projection.edges.len(), 1);
        assert_eq!(result.projection.edges[0].target_note_id, "target");
    }

    #[test]
    fn resolves_windows_separator_and_unicode_equivalent_exact_paths() {
        let windows_nfd_path = "Contexts\\기능\\Café.md".nfd().collect::<String>();
        let notes = vec![
            note("source", "Contexts/source.md", GraphIndexStatus::Indexed),
            note("target", &windows_nfd_path, GraphIndexStatus::Indexed),
            note(
                "same-stem",
                "Contexts/other/Café.md",
                GraphIndexStatus::Indexed,
            ),
        ];
        let edges = vec![unresolved_edge(
            "windows-unicode-edge",
            "source",
            "Contexts/기능/Café.md",
            "related",
        )];
        let request = match GraphComputeRequest::new(notes, edges, None, 10, Vec::new(), Vec::new())
        {
            Ok(value) => value,
            Err(error) => unreachable!("valid graph request rejected: {error}"),
        };
        let result = match compute_graph(request) {
            Ok(value) => value,
            Err(error) => unreachable!("graph compute failed: {error}"),
        };

        assert!(result.issues.is_empty());
        assert_eq!(result.projection.edges.len(), 1);
        assert_eq!(result.projection.edges[0].target_note_id, "target");
    }

    #[test]
    fn rejects_nfc_colliding_paths_as_ambiguous() {
        let nfd_path = "Contexts/기능/Café.md".nfd().collect::<String>();
        let notes = vec![
            note("source", "Contexts/source.md", GraphIndexStatus::Indexed),
            note(
                "target-nfc",
                "Contexts/기능/Café.md",
                GraphIndexStatus::Indexed,
            ),
            note("target-nfd", &nfd_path, GraphIndexStatus::Indexed),
        ];
        let edges = vec![unresolved_edge(
            "collision-edge",
            "source",
            "Contexts/기능/Café.md",
            "related",
        )];
        let request = match GraphComputeRequest::new(notes, edges, None, 10, Vec::new(), Vec::new())
        {
            Ok(value) => value,
            Err(error) => unreachable!("valid graph request rejected: {error}"),
        };
        let result = match compute_graph(request) {
            Ok(value) => value,
            Err(error) => unreachable!("graph compute failed: {error}"),
        };

        assert!(result.projection.edges.is_empty());
        assert_eq!(result.issues.len(), 1);
        assert_eq!(
            result.issues[0].code,
            GraphProjectionIssueCode::AmbiguousTargetNote
        );
    }
}
