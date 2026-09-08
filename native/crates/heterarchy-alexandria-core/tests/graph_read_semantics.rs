use heterarchy_alexandria_core::graph_compute::{
    GraphContextSignal, GraphProjection, GraphProjectionEdge, GraphProjectionNode,
    GraphReadDirection, read_projection,
};

fn node(note_id: &str, alexandria_type: &str) -> GraphProjectionNode {
    GraphProjectionNode {
        note_id: note_id.to_owned(),
        relative_path: format!("Contexts/{note_id}.md"),
        alexandria_type: alexandria_type.to_owned(),
        title: format!("Title {note_id}"),
        status: "active".to_owned(),
        project: None,
    }
}

fn edge(
    edge_id: &str,
    source_note_id: &str,
    target_note_id: &str,
    relation: &str,
    confidence: f64,
) -> GraphProjectionEdge {
    GraphProjectionEdge {
        edge_id: edge_id.to_owned(),
        source_note_id: source_note_id.to_owned(),
        source_path: format!("Contexts/{source_note_id}.md"),
        target_note_id: target_note_id.to_owned(),
        target_path: format!("Contexts/{target_note_id}.md"),
        relation: relation.to_owned(),
        confidence,
        source_kind: "frontmatter".to_owned(),
    }
}

fn weighted_projection() -> GraphProjection {
    GraphProjection {
        nodes: vec![
            node("seed", "context"),
            node("incoming", "context"),
            node("outgoing", "context"),
            node("tie", "context"),
        ],
        edges: vec![
            edge("edge-z", "seed", "tie", "related", 0.4),
            edge("edge-a", "seed", "tie", "cites", 0.1),
            edge("edge-m", "incoming", "seed", "derived_from", 0.0),
            edge("edge-o", "seed", "outgoing", "related", 0.2),
            edge("edge-self", "seed", "seed", "contains", 0.2),
        ],
    }
}

#[test]
fn related_notes_match_weight_direction_dedup_and_stable_order() {
    let projection = weighted_projection();
    let evidence_ids = Vec::new();
    let result = match read_projection(&projection, Some("seed"), 10, &evidence_ids) {
        Ok(value) => value,
        Err(error) => unreachable!("valid graph read failed: {error}"),
    };

    assert_eq!(result.related_notes.len(), 4);
    assert_eq!(result.related_notes[0].note_id, "tie");
    assert_eq!(result.related_notes[0].edge_id, "edge-a");
    assert!((result.related_notes[0].score - 1.0).abs() < 1e-12);
    assert_eq!(
        result.related_notes[0].direction,
        GraphReadDirection::Outgoing
    );
    assert_eq!(result.related_notes[1].note_id, "incoming");
    assert_eq!(result.related_notes[1].edge_id, "edge-m");
    assert_eq!(
        result.related_notes[1].direction,
        GraphReadDirection::Incoming
    );
    assert_eq!(result.related_notes[2].note_id, "outgoing");
    assert!((result.related_notes[2].score - 0.8).abs() < 1e-12);
    assert_eq!(result.related_notes[3].note_id, "seed");
    assert_eq!(result.related_notes[3].edge_id, "edge-self");
    assert_eq!(
        result.related_notes[3].direction,
        GraphReadDirection::Outgoing
    );
    assert!((result.related_notes[3].score - 0.6).abs() < 1e-12);

    let limited = match read_projection(&projection, Some("seed"), 2, &evidence_ids) {
        Ok(value) => value,
        Err(error) => unreachable!("valid limited graph read failed: {error}"),
    };
    assert_eq!(limited.related_notes.len(), 2);
    assert!(limited.context_evidence.is_empty());
}

#[test]
fn context_evidence_maps_all_signal_categories_and_filters_recalled_endpoints() {
    let projection = GraphProjection {
        nodes: vec![
            node("source", "context"),
            node("duplicate", "context"),
            node("superseded", "context"),
            node("impact", "context"),
            node("lineage", "context"),
            node("resume", "memory_compact"),
            node("proximity", "context"),
            node("unrecalled", "context"),
        ],
        edges: vec![
            edge("edge-duplicate", "source", "duplicate", "duplicates", 0.0),
            edge("edge-supersedes", "source", "superseded", "supersedes", 0.0),
            edge("edge-impact", "source", "impact", "blocks", 0.0),
            edge("edge-lineage", "source", "lineage", "derived_from", 0.0),
            edge("edge-resume", "source", "resume", "related", 0.0),
            edge("edge-proximity", "source", "proximity", "related", 0.0),
            edge("edge-unrecalled", "unrecalled", "source", "related", 0.0),
        ],
    };
    let recalled = [
        "source".to_owned(),
        "duplicate".to_owned(),
        "superseded".to_owned(),
        "impact".to_owned(),
        "lineage".to_owned(),
        "resume".to_owned(),
        "proximity".to_owned(),
    ];
    let result = match read_projection(&projection, None, 1, &recalled) {
        Ok(value) => value,
        Err(error) => unreachable!("valid context evidence read failed: {error}"),
    };

    assert_eq!(
        result
            .context_evidence
            .iter()
            .map(|item| (item.edge_id.as_str(), item.signal))
            .collect::<Vec<_>>(),
        vec![
            ("edge-duplicate", GraphContextSignal::DuplicateCandidate),
            ("edge-impact", GraphContextSignal::ImpactAnalysis),
            ("edge-lineage", GraphContextSignal::Lineage),
            ("edge-proximity", GraphContextSignal::GraphProximity),
            ("edge-resume", GraphContextSignal::ResumePath),
            ("edge-supersedes", GraphContextSignal::SupersedesCandidate),
        ]
    );
    assert_eq!(result.context_evidence[4].target_title, "Title resume");
}

#[test]
fn read_projection_rejects_invalid_limits_confidence_and_graph_endpoints() {
    let projection = weighted_projection();
    let empty = Vec::new();

    let Err(limit_error) = read_projection(&projection, Some("seed"), 0, &empty) else {
        unreachable!("zero read limit must fail");
    };
    assert!(limit_error.to_string().contains("limit must be between 1"));

    let mut nonfinite = projection.clone();
    nonfinite.edges[0].confidence = f64::NAN;
    let Err(confidence_error) = read_projection(&nonfinite, Some("seed"), 1, &empty) else {
        unreachable!("non-finite confidence must fail");
    };
    assert!(
        confidence_error
            .to_string()
            .contains("confidence must be finite")
    );

    let mut duplicate_nodes = projection.clone();
    duplicate_nodes.nodes.push(node("seed", "context"));
    let Err(duplicate_error) = read_projection(&duplicate_nodes, Some("seed"), 1, &empty) else {
        unreachable!("duplicate projected nodes must fail");
    };
    assert!(
        duplicate_error
            .to_string()
            .contains("projected node identity is duplicated")
    );

    let mut missing_endpoint = projection;
    missing_endpoint.edges.push(edge(
        "edge-missing",
        "missing-source",
        "seed",
        "related",
        0.0,
    ));
    let Err(endpoint_error) = read_projection(&missing_endpoint, Some("seed"), 1, &empty) else {
        unreachable!("missing projected endpoints must fail");
    };
    assert!(
        endpoint_error
            .to_string()
            .contains("missing source node missing-source")
    );
}

#[test]
fn missing_related_seed_and_empty_evidence_are_empty_successes() {
    let projection = weighted_projection();
    let empty = Vec::new();
    let result = match read_projection(&projection, Some("missing"), 1, &empty) {
        Ok(value) => value,
        Err(error) => unreachable!("missing seed read failed: {error}"),
    };
    assert!(result.related_notes.is_empty());
    assert!(result.context_evidence.is_empty());

    let result = match read_projection(&projection, None, 1, &empty) {
        Ok(value) => value,
        Err(error) => unreachable!("evidence-only read failed: {error}"),
    };
    assert!(result.related_notes.is_empty());
    assert!(result.context_evidence.is_empty());
}
