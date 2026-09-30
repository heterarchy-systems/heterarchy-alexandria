//! Strict graph orphan census and relation-suggestion wire adapter.

use std::collections::BTreeMap;

use heterarchy_alexandria_core::ComputeContractVersion;
use heterarchy_alexandria_core::document_analysis::{DocumentId, RelativeVaultPath};
use heterarchy_alexandria_core::graph_compute::{
    GRAPH_COMPUTE_VERSION, GraphDiagnosticsRequest, GraphOrphanCensusRequest,
    GraphRelationSuggestionRequest, GraphSourceEdge, GraphSourceNote, compute_graph_diagnostics,
};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphDiagnosticsWire {
    contract_version: u16,
    graph_compute_version: u16,
    notes: Vec<GraphDiagnosticNoteWire>,
    edges: Vec<GraphDiagnosticEdgeWire>,
    orphan_census: Option<GraphOrphanCensusWire>,
    relation_suggestions: Option<GraphRelationSuggestionWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphDiagnosticNoteWire {
    note_id: String,
    relative_path: String,
    title: String,
    project: Option<String>,
    tags: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphDiagnosticEdgeWire {
    edge_id: String,
    source_note_id: String,
    target_note_id: Option<String>,
    relation: String,
    source_kind: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphOrphanCensusWire {
    project: Option<String>,
    cursor: Option<String>,
    limit: usize,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphRelationSuggestionWire {
    seed_note_id: String,
    limit: usize,
}

/// Execute the coarse native graph diagnostics kernel.
pub(crate) fn compute_graph_diagnostics_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: GraphDiagnosticsWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_GRAPH_DIAGNOSTICS_INPUT_ERROR: {error}"))?;
    crate::validate_contract_version(
        wire.contract_version,
        "NATIVE_GRAPH_DIAGNOSTICS_CONTRACT_ERROR",
    )?;
    if wire.graph_compute_version != GRAPH_COMPUTE_VERSION {
        return Err(format!(
            "NATIVE_GRAPH_DIAGNOSTICS_CONTRACT_ERROR: expected graph compute version {GRAPH_COMPUTE_VERSION}, found {}",
            wire.graph_compute_version
        ));
    }
    let mut tags = BTreeMap::new();
    let notes = wire
        .notes
        .into_iter()
        .map(|note| {
            let note_id = DocumentId::new(note.note_id.clone())
                .map_err(|error| format!("NATIVE_GRAPH_DIAGNOSTICS_INPUT_ERROR: {error}"))?;
            let relative_path = RelativeVaultPath::new(note.relative_path.clone())
                .map_err(|error| format!("NATIVE_GRAPH_DIAGNOSTICS_INPUT_ERROR: {error}"))?;
            tags.insert(note.note_id, note.tags);
            Ok(GraphSourceNote {
                note_id,
                relative_path,
                alexandria_type: "context".to_owned(),
                title: note.title,
                status: "active".to_owned(),
                project: note.project,
                aliases: Vec::new(),
                index_status: heterarchy_alexandria_core::graph_compute::GraphIndexStatus::Indexed,
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
    let edges = wire
        .edges
        .into_iter()
        .map(|edge| {
            let source_path = edge.source_note_id.clone();
            let target_path = edge
                .target_note_id
                .clone()
                .unwrap_or_else(|| "unresolved".to_owned());
            GraphSourceEdge {
                edge_id: edge.edge_id,
                source_note_id: edge.source_note_id,
                source_path,
                target_note_id: edge.target_note_id,
                target_path,
                relation: edge.relation,
                confidence: 1.0,
                source_kind: edge.source_kind,
            }
        })
        .collect();
    let request = GraphDiagnosticsRequest {
        notes,
        edges,
        tags,
        orphan_census: wire.orphan_census.map(|item| GraphOrphanCensusRequest {
            project: item.project,
            cursor: item.cursor,
            limit: item.limit,
        }),
        relation_suggestions: wire.relation_suggestions.map(|item| {
            GraphRelationSuggestionRequest {
                seed_note_id: item.seed_note_id,
                limit: item.limit,
            }
        }),
    };
    let result = compute_graph_diagnostics(
        request,
        ComputeContractVersion::CURRENT.value(),
        GRAPH_COMPUTE_VERSION,
    )
    .map_err(|error| format!("NATIVE_GRAPH_DIAGNOSTICS_INVARIANT_ERROR: {error}"))?;
    serde_json::to_vec(&result)
        .map_err(|error| format!("NATIVE_GRAPH_DIAGNOSTICS_OUTPUT_ERROR: {error}"))
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use super::compute_graph_diagnostics_payload;
    use serde_json::Value;

    #[test]
    fn diagnostics_returns_degree_and_parent_debt() -> Result<(), Box<dyn Error>> {
        let payload = br#"{
            "contract_version":1,
            "graph_compute_version":1,
            "notes":[
                {"note_id":"orphan","relative_path":"Contexts/orphan.md","title":"Orphan","project":"p","tags":[]},
                {"note_id":"linked","relative_path":"Contexts/linked.md","title":"Linked","project":"p","tags":[]},
                {"note_id":"parent","relative_path":"Contexts/parent.md","title":"Parent","project":"p","tags":[]}
            ],
            "edges":[
                {"edge_id":"e1","source_note_id":"linked","target_note_id":"parent","relation":"wikilink","source_kind":"wikilink"}
            ],
            "orphan_census":{"project":"p","cursor":null,"limit":10},
            "relation_suggestions":null
        }"#;
        let encoded = compute_graph_diagnostics_payload(payload)?;
        let value: Value = serde_json::from_slice(&encoded)?;
        assert_eq!(value["total_orphans"], 3);
        assert_eq!(value["orphans"][0]["relative_path"], "Contexts/linked.md");
        assert_eq!(value["orphans"][0]["has_wikilink_connectivity"], true);
        assert_eq!(value["orphans"][1]["debt_kinds"][0], "degree_zero");
        Ok(())
    }
}
