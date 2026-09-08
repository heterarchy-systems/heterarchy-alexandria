//! Deterministic one-hop graph reads over an already-built projection.

use std::collections::{BTreeMap, BTreeSet};

use serde::Serialize;

use super::{
    GraphComputeError, GraphProjection, GraphProjectionEdge, GraphProjectionNode,
    MAX_SELECTED_GRAPH_CANDIDATES, MAX_TRAVERSAL_RESULTS, traverse_projection,
};

const RESUME_PATH_TYPES: [&str; 3] = ["memory_compact", "job_plan", "implementation_history"];

/// Direction of a projected edge relative to a requested note.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphReadDirection {
    /// The requested note is the edge source.
    Outgoing,
    /// The requested note is the edge target.
    Incoming,
}

/// Semantic signal assigned to one recalled graph edge.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphContextSignal {
    /// The edge indicates a possible duplicate.
    DuplicateCandidate,
    /// The edge indicates a possible supersession.
    SupersedesCandidate,
    /// The edge indicates an impact relationship.
    ImpactAnalysis,
    /// The edge indicates lineage or derivation.
    Lineage,
    /// The target note is a resumable artifact.
    ResumePath,
    /// The edge supplies general graph proximity evidence.
    GraphProximity,
}

/// One weighted one-hop note related to a requested seed.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GraphRelatedNote {
    /// Related note identity.
    pub note_id: String,
    /// Projected edge identity selected for this related note.
    pub edge_id: String,
    /// Projected relation kind.
    pub relation: String,
    /// Projected edge provenance.
    pub source_kind: String,
    /// Direction relative to the requested seed.
    pub direction: GraphReadDirection,
    /// Relation weight plus projected confidence.
    pub score: f64,
}

/// One directly recalled edge whose endpoints are both in the recalled set.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphContextEvidence {
    /// Semantic signal assigned to the edge.
    pub signal: GraphContextSignal,
    /// Projected edge identity.
    pub edge_id: String,
    /// Source note identity.
    pub source_note_id: String,
    /// Target note identity.
    pub target_note_id: String,
    /// Current target note title.
    pub target_title: String,
    /// Projected relation kind.
    pub relation: String,
}

/// Deterministic related-note and context-evidence results for one projection read.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GraphProjectionReadResult {
    /// Weighted one-hop related notes in stable order.
    pub related_notes: Vec<GraphRelatedNote>,
    /// Recalled direct edge evidence in edge identity order.
    pub context_evidence: Vec<GraphContextEvidence>,
}

/// Read one already-built graph projection without rebuilding or persisting it.
///
/// # Errors
///
/// Returns an error when the projection has duplicate or missing edge endpoints, an edge
/// confidence is non-finite, the related-note limit is outside the bounded contract, or the
/// recalled-note set exceeds the native input bound.
pub fn read_projection(
    projection: &GraphProjection,
    related_note_id: Option<&str>,
    limit: usize,
    evidence_note_ids: &[String],
) -> Result<GraphProjectionReadResult, GraphComputeError> {
    if limit == 0 || limit > MAX_TRAVERSAL_RESULTS {
        return Err(GraphComputeError::new(format!(
            "limit must be between 1 and {MAX_TRAVERSAL_RESULTS}"
        )));
    }
    if evidence_note_ids.len() > MAX_SELECTED_GRAPH_CANDIDATES {
        return Err(GraphComputeError::new(format!(
            "evidence note count exceeds the {MAX_SELECTED_GRAPH_CANDIDATES} item limit"
        )));
    }
    for edge in &projection.edges {
        if !edge.confidence.is_finite() {
            return Err(GraphComputeError::new(format!(
                "edge {} confidence must be finite",
                edge.edge_id
            )));
        }
    }

    // Reuse the existing graph-index validator so read semantics reject malformed snapshots
    // with the same endpoint and duplicate-node contract as traversal.
    let _ = traverse_projection(projection, &[])?;
    let nodes = projection
        .nodes
        .iter()
        .map(|node| (node.note_id.as_str(), node))
        .collect::<BTreeMap<_, _>>();
    let related_notes = match related_note_id {
        Some(note_id) => related_notes(projection, &nodes, note_id, limit)?,
        None => Vec::new(),
    };
    let context_evidence = context_evidence(projection, &nodes, evidence_note_ids);
    Ok(GraphProjectionReadResult {
        related_notes,
        context_evidence,
    })
}

fn related_notes(
    projection: &GraphProjection,
    nodes: &BTreeMap<&str, &GraphProjectionNode>,
    note_id: &str,
    limit: usize,
) -> Result<Vec<GraphRelatedNote>, GraphComputeError> {
    if !nodes.contains_key(note_id) {
        return Ok(Vec::new());
    }
    let mut best = BTreeMap::<String, GraphRelatedNote>::new();
    for edge in &projection.edges {
        let Some(candidate) = related_candidate(edge, note_id, nodes) else {
            continue;
        };
        if !candidate.score.is_finite() {
            return Err(GraphComputeError::new(format!(
                "edge {} related-note score must be finite",
                edge.edge_id
            )));
        }
        let replace = best.get(&candidate.note_id).is_none_or(|previous| {
            candidate.score > previous.score
                || (candidate.score.total_cmp(&previous.score) == std::cmp::Ordering::Equal
                    && candidate.edge_id < previous.edge_id)
        });
        if replace {
            best.insert(candidate.note_id.clone(), candidate);
        }
    }
    let mut ordered = best.into_values().collect::<Vec<_>>();
    ordered.sort_by(|left, right| {
        right
            .score
            .total_cmp(&left.score)
            .then_with(|| left.edge_id.cmp(&right.edge_id))
            .then_with(|| left.note_id.cmp(&right.note_id))
    });
    ordered.truncate(limit);
    Ok(ordered)
}

fn related_candidate(
    edge: &GraphProjectionEdge,
    note_id: &str,
    nodes: &BTreeMap<&str, &GraphProjectionNode>,
) -> Option<GraphRelatedNote> {
    let (related_id, direction) = if edge.source_note_id == note_id
        && nodes.contains_key(edge.target_note_id.as_str())
    {
        (edge.target_note_id.as_str(), GraphReadDirection::Outgoing)
    } else if edge.target_note_id == note_id && nodes.contains_key(edge.source_note_id.as_str()) {
        (edge.source_note_id.as_str(), GraphReadDirection::Incoming)
    } else {
        return None;
    };
    Some(GraphRelatedNote {
        note_id: related_id.to_owned(),
        edge_id: edge.edge_id.clone(),
        relation: edge.relation.clone(),
        source_kind: edge.source_kind.clone(),
        direction,
        score: relation_weight(&edge.relation) + edge.confidence,
    })
}

fn context_evidence(
    projection: &GraphProjection,
    nodes: &BTreeMap<&str, &GraphProjectionNode>,
    evidence_note_ids: &[String],
) -> Vec<GraphContextEvidence> {
    if evidence_note_ids.is_empty() {
        return Vec::new();
    }
    let recalled = evidence_note_ids
        .iter()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let mut evidence = projection
        .edges
        .iter()
        .filter_map(|edge| {
            let target = nodes.get(edge.target_note_id.as_str()).copied()?;
            if !recalled.contains(edge.source_note_id.as_str())
                || !recalled.contains(edge.target_note_id.as_str())
            {
                return None;
            }
            Some(GraphContextEvidence {
                signal: context_signal(&edge.relation, &target.alexandria_type),
                edge_id: edge.edge_id.clone(),
                source_note_id: edge.source_note_id.clone(),
                target_note_id: edge.target_note_id.clone(),
                target_title: target.title.clone(),
                relation: edge.relation.clone(),
            })
        })
        .collect::<Vec<_>>();
    evidence.sort_by(|left, right| left.edge_id.cmp(&right.edge_id));
    evidence
}

fn relation_weight(relation: &str) -> f64 {
    match relation {
        "derived_from" => 1.0,
        "cites" => 0.9,
        "supersedes" | "promotes_to" | "duplicates" => 0.8,
        "supports" | "extends" => 0.7,
        "related" => 0.6,
        "wikilink" => 0.5,
        _ => 0.4,
    }
}

fn context_signal(relation: &str, target_type: &str) -> GraphContextSignal {
    if relation == "duplicates" {
        return GraphContextSignal::DuplicateCandidate;
    }
    if relation == "supersedes" {
        return GraphContextSignal::SupersedesCandidate;
    }
    if matches!(relation, "blocks" | "resolves" | "contradicts") {
        return GraphContextSignal::ImpactAnalysis;
    }
    if matches!(
        relation,
        "derived_from" | "promotes_to" | "supports" | "extends"
    ) {
        return GraphContextSignal::Lineage;
    }
    if RESUME_PATH_TYPES.contains(&target_type) {
        return GraphContextSignal::ResumePath;
    }
    GraphContextSignal::GraphProximity
}
