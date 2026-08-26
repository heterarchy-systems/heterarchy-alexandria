//! Strict active-projection graph traversal wire for retrieval-time multi-hop compute.

use heterarchy_alexandria_core::ComputeContractVersion;
use heterarchy_alexandria_core::graph_compute::{
    GRAPH_COMPUTE_VERSION, GraphProjection, GraphProjectionEdge, GraphProjectionNode,
    GraphSelectedCandidate, GraphTitleRelevance, GraphTraversalRequest, GraphTraversalResult,
    TraversalDirection, select_projection_candidates, traverse_projection,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphTraversalBatchWire {
    contract_version: u16,
    graph_compute_version: u16,
    projection: GraphProjectionWire,
    traversal_requests: Vec<GraphTraversalRequestWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphCandidateSelectionBatchWire {
    contract_version: u16,
    graph_compute_version: u16,
    projection: GraphProjectionWire,
    traversal_requests: Vec<GraphTraversalRequestWire>,
    primary_note_ids: Vec<String>,
    query: String,
    max_candidates: usize,
    min_shared_trigrams: usize,
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

#[derive(Debug, Serialize)]
struct GraphTraversalBatchResult {
    contract_version: u16,
    graph_compute_version: u16,
    traversals: Vec<GraphTraversalResult>,
}

#[derive(Debug, Serialize)]
struct GraphCandidateSelectionBatchResult {
    contract_version: u16,
    graph_compute_version: u16,
    traversals: Vec<GraphTraversalResult>,
    candidates: Vec<GraphSelectedCandidate>,
    primary_title_relevance: Vec<GraphTitleRelevance>,
}

/// Traverse one already-built graph projection without rebuilding projection state.
///
/// # Errors
///
/// Returns a stable machine-readable error when the wire contract, graph version, projection
/// snapshot, traversal direction, or bounded traversal request is invalid.
pub(crate) fn compute_graph_traversal_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: GraphTraversalBatchWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_GRAPH_TRAVERSAL_INPUT_ERROR: {error}"))?;
    crate::validate_contract_version(
        wire.contract_version,
        "NATIVE_GRAPH_TRAVERSAL_CONTRACT_ERROR",
    )?;
    if wire.graph_compute_version != GRAPH_COMPUTE_VERSION {
        return Err(format!(
            "NATIVE_GRAPH_TRAVERSAL_CONTRACT_ERROR: expected graph compute version {GRAPH_COMPUTE_VERSION}, found {}",
            wire.graph_compute_version
        ));
    }
    let projection = projection_from_wire(wire.projection)?;
    let requests = wire
        .traversal_requests
        .into_iter()
        .map(traversal_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let traversals = traverse_projection(&projection, &requests)
        .map_err(|error| format!("NATIVE_GRAPH_TRAVERSAL_INVARIANT_ERROR: {error}"))?;
    serde_json::to_vec(&GraphTraversalBatchResult {
        contract_version: ComputeContractVersion::CURRENT.value(),
        graph_compute_version: GRAPH_COMPUTE_VERSION,
        traversals,
    })
    .map_err(|error| format!("NATIVE_GRAPH_TRAVERSAL_OUTPUT_ERROR: {error}"))
}

/// Traverse one active projection and select a small title-relevant graph candidate set.
///
/// # Errors
///
/// Returns a stable machine-readable error when the wire contract, graph version, projection,
/// query, candidate bound, trigram threshold, or traversal request is invalid.
pub(crate) fn compute_graph_candidate_selection_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: GraphCandidateSelectionBatchWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_GRAPH_CANDIDATE_SELECTION_INPUT_ERROR: {error}"))?;
    crate::validate_contract_version(
        wire.contract_version,
        "NATIVE_GRAPH_CANDIDATE_SELECTION_CONTRACT_ERROR",
    )?;
    if wire.graph_compute_version != GRAPH_COMPUTE_VERSION {
        return Err(format!(
            "NATIVE_GRAPH_CANDIDATE_SELECTION_CONTRACT_ERROR: expected graph compute version {GRAPH_COMPUTE_VERSION}, found {}",
            wire.graph_compute_version
        ));
    }
    let projection = projection_from_wire(wire.projection)?;
    let requests = wire
        .traversal_requests
        .into_iter()
        .map(traversal_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let selection = select_projection_candidates(
        &projection,
        &requests,
        &wire.primary_note_ids,
        &wire.query,
        wire.max_candidates,
        wire.min_shared_trigrams,
    )
    .map_err(|error| format!("NATIVE_GRAPH_CANDIDATE_SELECTION_INVARIANT_ERROR: {error}"))?;
    serde_json::to_vec(&GraphCandidateSelectionBatchResult {
        contract_version: ComputeContractVersion::CURRENT.value(),
        graph_compute_version: GRAPH_COMPUTE_VERSION,
        traversals: selection.traversals,
        candidates: selection.candidates,
        primary_title_relevance: selection.primary_title_relevance,
    })
    .map_err(|error| format!("NATIVE_GRAPH_CANDIDATE_SELECTION_OUTPUT_ERROR: {error}"))
}

fn projection_from_wire(wire: GraphProjectionWire) -> Result<GraphProjection, String> {
    let edges = wire
        .edges
        .into_iter()
        .map(edge_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(GraphProjection {
        nodes: wire.nodes.into_iter().map(node_from_wire).collect(),
        edges,
    })
}

fn node_from_wire(node: GraphProjectionNodeWire) -> GraphProjectionNode {
    GraphProjectionNode {
        note_id: node.note_id,
        relative_path: node.relative_path,
        alexandria_type: node.alexandria_type,
        title: node.title,
        status: node.status,
        project: node.project,
    }
}

fn edge_from_wire(edge: GraphProjectionEdgeWire) -> Result<GraphProjectionEdge, String> {
    if !edge.confidence.is_finite() {
        return Err(format!(
            "NATIVE_GRAPH_TRAVERSAL_INPUT_ERROR: edge {} confidence must be finite",
            edge.edge_id
        ));
    }
    Ok(GraphProjectionEdge {
        edge_id: edge.edge_id,
        source_note_id: edge.source_note_id,
        source_path: edge.source_path,
        target_note_id: edge.target_note_id,
        target_path: edge.target_path,
        relation: edge.relation,
        confidence: edge.confidence,
        source_kind: edge.source_kind,
    })
}

fn traversal_from_wire(wire: GraphTraversalRequestWire) -> Result<GraphTraversalRequest, String> {
    Ok(GraphTraversalRequest {
        request_id: wire.request_id,
        start_note_id: wire.start_note_id,
        direction: direction_from_wire(&wire.direction)?,
        relations: wire.relations,
        max_depth: wire.max_depth,
        max_results: wire.max_results,
    })
}

fn direction_from_wire(value: &str) -> Result<TraversalDirection, String> {
    match value {
        "outgoing" => Ok(TraversalDirection::Outgoing),
        "incoming" => Ok(TraversalDirection::Incoming),
        "both" => Ok(TraversalDirection::Both),
        other => Err(format!(
            "NATIVE_GRAPH_TRAVERSAL_INPUT_ERROR: unknown graph traversal direction {other}"
        )),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::{compute_graph_candidate_selection_payload, compute_graph_traversal_payload};

    const VALID_PAYLOAD: &[u8] = br#"{
        "contract_version":1,
        "graph_compute_version":1,
        "projection":{
            "nodes":[
                {"note_id":"a","relative_path":"Contexts/a.md","alexandria_type":"context","title":"A","status":"active","project":null},
                {"note_id":"b","relative_path":"Contexts/b.md","alexandria_type":"context","title":"B","status":"active","project":null},
                {"note_id":"c","relative_path":"Contexts/c.md","alexandria_type":"context","title":"C","status":"active","project":null}
            ],
            "edges":[
                {"edge_id":"e1","source_note_id":"a","source_path":"Contexts/a.md","target_note_id":"b","target_path":"Contexts/b.md","relation":"wikilink","confidence":1.0,"source_kind":"wikilink"},
                {"edge_id":"e2","source_note_id":"b","source_path":"Contexts/b.md","target_note_id":"c","target_path":"Contexts/c.md","relation":"wikilink","confidence":1.0,"source_kind":"wikilink"}
            ]
        },
        "traversal_requests":[
            {"request_id":"depth-two","start_note_id":"a","direction":"outgoing","relations":["wikilink"],"max_depth":2,"max_results":10}
        ]
    }"#;

    #[test]
    fn adapter_traverses_active_projection_in_one_coarse_request() {
        let encoded = match compute_graph_traversal_payload(VALID_PAYLOAD) {
            Ok(value) => value,
            Err(error) => unreachable!("valid graph traversal payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("graph traversal adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["contract_version"], 1);
        assert_eq!(decoded["graph_compute_version"], 1);
        assert_eq!(decoded["traversals"][0]["start_found"], true);
        assert_eq!(
            decoded["traversals"][0]["visits"],
            serde_json::json!([
                {"note_id":"a","depth":0},
                {"note_id":"b","depth":1},
                {"note_id":"c","depth":2}
            ])
        );
    }

    #[test]
    fn adapter_rejects_unknown_fields_and_graph_versions() {
        let extra_field = VALID_PAYLOAD
            .strip_suffix(b"}")
            .map(|prefix| [prefix, br#","extra":true}"#].concat())
            .unwrap_or_default();
        let Err(field_error) = compute_graph_traversal_payload(&extra_field) else {
            unreachable!("unknown graph traversal field must fail");
        };
        assert!(field_error.contains("unknown field"));

        let version_payload = VALID_PAYLOAD
            .windows(b"\"graph_compute_version\":1".len())
            .position(|window| window == b"\"graph_compute_version\":1")
            .map(|position| {
                let mut payload = VALID_PAYLOAD.to_vec();
                let version_index = position + b"\"graph_compute_version\":".len();
                payload[version_index] = b'2';
                payload
            })
            .unwrap_or_default();
        let Err(version_error) = compute_graph_traversal_payload(&version_payload) else {
            unreachable!("unknown graph traversal version must fail");
        };
        assert!(version_error.contains("expected graph compute version 1, found 2"));
    }

    #[test]
    fn adapter_selects_a_small_title_relevant_graph_candidate_set() {
        let payload = br#"{
            "contract_version":1,
            "graph_compute_version":1,
            "projection":{
                "nodes":[
                    {"note_id":"seed","relative_path":"Contexts/seed.md","alexandria_type":"context","title":"Migration Plan","status":"active","project":null},
                    {"note_id":"target","relative_path":"Contexts/target.md","alexandria_type":"context","title":"Runtime Seal Verification","status":"active","project":null},
                    {"note_id":"noise","relative_path":"Contexts/noise.md","alexandria_type":"context","title":"Unrelated Notes","status":"active","project":null}
                ],
                "edges":[
                    {"edge_id":"e1","source_note_id":"seed","source_path":"Contexts/seed.md","target_note_id":"target","target_path":"Contexts/target.md","relation":"wikilink","confidence":1.0,"source_kind":"wikilink"},
                    {"edge_id":"e2","source_note_id":"seed","source_path":"Contexts/seed.md","target_note_id":"noise","target_path":"Contexts/noise.md","relation":"wikilink","confidence":1.0,"source_kind":"wikilink"}
                ]
            },
            "traversal_requests":[
                {"request_id":"select","start_note_id":"seed","direction":"outgoing","relations":["wikilink"],"max_depth":1,"max_results":10}
            ],
            "primary_note_ids":["seed"],
            "query":"runtime seal status check",
            "max_candidates":1,
            "min_shared_trigrams":3
        }"#;
        let encoded = match compute_graph_candidate_selection_payload(payload) {
            Ok(value) => value,
            Err(error) => unreachable!("valid graph candidate selection failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("graph candidate selector emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["candidates"][0]["note_id"], "target");
        assert_eq!(decoded["candidates"][0]["min_depth"], 1);
        assert_eq!(decoded["candidates"][0]["seed_support"], 1);
        assert!(
            decoded["candidates"][0]["shared_title_trigrams"]
                .as_u64()
                .is_some_and(|value| value >= 3)
        );
        assert_eq!(decoded["primary_title_relevance"][0]["note_id"], "seed");
    }
}
