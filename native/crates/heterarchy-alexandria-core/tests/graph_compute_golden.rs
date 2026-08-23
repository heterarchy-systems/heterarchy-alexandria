//! Live-Python projection and independent graph-algorithm golden parity.

use heterarchy_alexandria_core::document_analysis::{DocumentId, RelativeVaultPath};
use heterarchy_alexandria_core::graph_compute::{
    GraphComputeRequest, GraphIndexStatus, GraphLineageRequest, GraphProjection,
    GraphProjectionEdge, GraphProjectionNode, GraphSourceEdge, GraphSourceNote,
    GraphTraversalRequest, TraversalDirection, compute_graph,
};
use serde::Deserialize;
use serde_json::Value;

const GOLDEN_CORPUS: &str = include_str!("../../../corpora/graph_compute/v1/cases.json");

#[derive(Debug, Deserialize)]
struct GoldenCorpus {
    schema_version: u16,
    feature: String,
    cases: Vec<GoldenCase>,
}

#[derive(Debug, Deserialize)]
struct GoldenCase {
    case_id: String,
    batch_size: usize,
    source_notes: Vec<GoldenSourceNote>,
    source_edges: Vec<GoldenSourceEdge>,
    previous_projection: Option<GoldenProjection>,
    traversal_requests: Vec<GoldenTraversalRequest>,
    lineage_requests: Vec<GoldenLineageRequest>,
    expected: Value,
}

#[derive(Debug, Deserialize)]
struct GoldenSourceNote {
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
struct GoldenSourceEdge {
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
struct GoldenProjection {
    nodes: Vec<GoldenProjectionNode>,
    edges: Vec<GoldenProjectionEdge>,
}

#[derive(Debug, Deserialize)]
struct GoldenProjectionNode {
    note_id: String,
    relative_path: String,
    alexandria_type: String,
    title: String,
    status: String,
    project: Option<String>,
}

#[derive(Debug, Deserialize)]
struct GoldenProjectionEdge {
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
struct GoldenTraversalRequest {
    request_id: String,
    start_note_id: String,
    direction: String,
    relations: Vec<String>,
    max_depth: usize,
    max_results: usize,
}

#[derive(Debug, Deserialize)]
struct GoldenLineageRequest {
    request_id: String,
    note_id: String,
    max_depth: usize,
    max_results: usize,
}

#[test]
fn graph_compute_matches_frozen_pre_cutover_corpus() {
    let corpus: GoldenCorpus = match serde_json::from_str(GOLDEN_CORPUS) {
        Ok(value) => value,
        Err(error) => unreachable!("graph corpus must be valid JSON: {error}"),
    };
    assert_eq!(corpus.schema_version, 1);
    assert_eq!(corpus.feature, "graph_compute");

    for case in &corpus.cases {
        let request = match request_from_case(case) {
            Ok(value) => value,
            Err(error) => unreachable!("{} input conversion failed: {error}", case.case_id),
        };
        let result = match compute_graph(request) {
            Ok(value) => value,
            Err(error) => unreachable!("{} graph compute failed: {error}", case.case_id),
        };
        assert_eq!(result.contract_version, 1);
        assert_eq!(result.graph_compute_version, 1);
        let encoded = match serde_json::to_value(&result) {
            Ok(value) => value,
            Err(error) => unreachable!("{} result must serialize: {error}", case.case_id),
        };
        for field in [
            "projection",
            "batches",
            "issues",
            "metrics",
            "structural_diagnostics",
            "analysis",
        ] {
            assert_eq!(
                encoded.get(field),
                case.expected.get(field),
                "{} field {field}",
                case.case_id
            );
        }
    }
}

fn request_from_case(case: &GoldenCase) -> Result<GraphComputeRequest, String> {
    let notes = case
        .source_notes
        .iter()
        .map(source_note)
        .collect::<Result<Vec<_>, _>>()?;
    let edges = case.source_edges.iter().map(source_edge).collect();
    let previous = case.previous_projection.as_ref().map(previous_projection);
    let traversals = case
        .traversal_requests
        .iter()
        .map(traversal_request)
        .collect::<Result<Vec<_>, _>>()?;
    let lineages = case
        .lineage_requests
        .iter()
        .map(|request| GraphLineageRequest {
            request_id: request.request_id.clone(),
            note_id: request.note_id.clone(),
            max_depth: request.max_depth,
            max_results: request.max_results,
        })
        .collect();
    GraphComputeRequest::new(
        notes,
        edges,
        previous,
        case.batch_size,
        traversals,
        lineages,
    )
    .map_err(|error| error.to_string())
}

fn source_note(value: &GoldenSourceNote) -> Result<GraphSourceNote, String> {
    let note_id = DocumentId::new(value.note_id.clone()).map_err(|error| error.to_string())?;
    let relative_path =
        RelativeVaultPath::new(value.relative_path.clone()).map_err(|error| error.to_string())?;
    Ok(GraphSourceNote {
        note_id,
        relative_path,
        alexandria_type: value.alexandria_type.clone(),
        title: value.title.clone(),
        status: value.status.clone(),
        project: value.project.clone(),
        aliases: value.aliases.clone(),
        index_status: parse_index_status(&value.index_status)?,
    })
}

fn source_edge(value: &GoldenSourceEdge) -> GraphSourceEdge {
    GraphSourceEdge {
        edge_id: value.edge_id.clone(),
        source_note_id: value.source_note_id.clone(),
        source_path: value.source_path.clone(),
        target_note_id: value.target_note_id.clone(),
        target_path: value.target_path.clone(),
        relation: value.relation.clone(),
        confidence: value.confidence,
        source_kind: value.source_kind.clone(),
    }
}

fn previous_projection(value: &GoldenProjection) -> GraphProjection {
    GraphProjection {
        nodes: value
            .nodes
            .iter()
            .map(|node| GraphProjectionNode {
                note_id: node.note_id.clone(),
                relative_path: node.relative_path.clone(),
                alexandria_type: node.alexandria_type.clone(),
                title: node.title.clone(),
                status: node.status.clone(),
                project: node.project.clone(),
            })
            .collect(),
        edges: value
            .edges
            .iter()
            .map(|edge| GraphProjectionEdge {
                edge_id: edge.edge_id.clone(),
                source_note_id: edge.source_note_id.clone(),
                source_path: edge.source_path.clone(),
                target_note_id: edge.target_note_id.clone(),
                target_path: edge.target_path.clone(),
                relation: edge.relation.clone(),
                confidence: edge.confidence,
                source_kind: edge.source_kind.clone(),
            })
            .collect(),
    }
}

fn traversal_request(value: &GoldenTraversalRequest) -> Result<GraphTraversalRequest, String> {
    Ok(GraphTraversalRequest {
        request_id: value.request_id.clone(),
        start_note_id: value.start_note_id.clone(),
        direction: parse_direction(&value.direction)?,
        relations: value.relations.clone(),
        max_depth: value.max_depth,
        max_results: value.max_results,
    })
}

fn parse_index_status(value: &str) -> Result<GraphIndexStatus, String> {
    match value {
        "indexed" => Ok(GraphIndexStatus::Indexed),
        "stale" => Ok(GraphIndexStatus::Stale),
        "error" => Ok(GraphIndexStatus::Error),
        other => Err(format!("unknown graph index status: {other}")),
    }
}

fn parse_direction(value: &str) -> Result<TraversalDirection, String> {
    match value {
        "outgoing" => Ok(TraversalDirection::Outgoing),
        "incoming" => Ok(TraversalDirection::Incoming),
        "both" => Ok(TraversalDirection::Both),
        other => Err(format!("unknown traversal direction: {other}")),
    }
}
