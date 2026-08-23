//! Python-compatible projection source normalization and target resolution.

use std::collections::{BTreeMap, BTreeSet};

use caseless::default_case_fold_str;
use unicode_normalization::UnicodeNormalization;

use super::{
    AmbiguousLinkName, GraphIndexStatus, GraphProjection, GraphProjectionBatch,
    GraphProjectionEdge, GraphProjectionIssue, GraphProjectionIssueCode, GraphProjectionMetrics,
    GraphProjectionNode, GraphSourceEdge, GraphSourceNote, GraphStructuralDiagnostics,
};

pub(super) struct ProjectionBuildResult {
    pub projection: GraphProjection,
    pub batches: Vec<GraphProjectionBatch>,
    pub issues: Vec<GraphProjectionIssue>,
    pub metrics: GraphProjectionMetrics,
    pub structural_diagnostics: GraphStructuralDiagnostics,
}

pub(super) fn build_projection(
    source_notes: Vec<GraphSourceNote>,
    source_edges: Vec<GraphSourceEdge>,
    batch_size: usize,
) -> ProjectionBuildResult {
    let scanned = source_notes.len().saturating_add(source_edges.len());
    let duplicate_note_ids = duplicate_note_ids(&source_notes);
    let duplicate_edge_ids = duplicate_edge_ids(&source_edges);
    let mut issues = index_error_issues(&source_notes);
    let notes = canonical_notes(source_notes);
    let edges = canonical_edges(source_edges);
    let indexed_notes = notes
        .iter()
        .filter(|note| note.index_status == GraphIndexStatus::Indexed)
        .collect::<Vec<_>>();
    let notes_by_id = indexed_notes_by_id(&indexed_notes);
    let notes_by_path = indexed_notes_by_path(&indexed_notes);
    let notes_by_link_name = notes_by_link_name(&indexed_notes);
    let projection_nodes = indexed_notes
        .iter()
        .map(|note| projection_node(note))
        .collect::<Vec<_>>();
    let edge_result = projection_edges(
        &edges,
        &indexed_notes,
        &notes_by_id,
        &notes_by_path,
        &notes_by_link_name,
    );
    issues.extend(edge_result.issues);
    issues.sort_by(issue_sort_key);
    let projection = GraphProjection {
        nodes: projection_nodes,
        edges: edge_result.edges,
    };
    let indexed = projection
        .nodes
        .len()
        .saturating_add(projection.edges.len());
    let metrics = GraphProjectionMetrics {
        scanned,
        indexed,
        updated: 0,
        skipped: scanned.saturating_sub(indexed),
        errors: issues.len(),
    };
    let batches = projection_batches(&projection, batch_size);
    let structural_diagnostics = GraphStructuralDiagnostics {
        duplicate_note_ids,
        duplicate_edge_ids,
        ambiguous_link_names: ambiguous_link_names(&indexed_notes, &notes_by_link_name),
    };
    ProjectionBuildResult {
        projection,
        batches,
        issues,
        metrics,
        structural_diagnostics,
    }
}

fn canonical_notes(mut notes: Vec<GraphSourceNote>) -> Vec<GraphSourceNote> {
    notes.sort_by(|left, right| note_sort_key(left).cmp(&note_sort_key(right)));
    notes.dedup_by(|right, left| right.note_id == left.note_id);
    notes
}

fn note_sort_key(note: &GraphSourceNote) -> (&str, &str, &str, &str, Option<&str>, u8) {
    (
        note.note_id.as_str(),
        note.relative_path.as_str(),
        note.title.as_str(),
        note.status.as_str(),
        note.project.as_deref(),
        index_status_rank(note.index_status),
    )
}

const fn index_status_rank(status: GraphIndexStatus) -> u8 {
    match status {
        GraphIndexStatus::Indexed => 0,
        GraphIndexStatus::Stale => 1,
        GraphIndexStatus::Error => 2,
    }
}

fn canonical_edges(mut edges: Vec<GraphSourceEdge>) -> Vec<GraphSourceEdge> {
    edges.sort_by(|left, right| edge_sort_key(left).cmp(&edge_sort_key(right)));
    edges.dedup_by(|right, left| right.edge_id == left.edge_id);
    edges
}

fn edge_sort_key(edge: &GraphSourceEdge) -> (&str, &str, &str, &str, &str, &str, u64) {
    (
        edge.edge_id.as_str(),
        edge.source_note_id.as_str(),
        edge.target_note_id.as_deref().unwrap_or(""),
        edge.target_path.as_str(),
        edge.relation.as_str(),
        edge.source_kind.as_str(),
        edge.confidence.to_bits(),
    )
}

fn duplicate_note_ids(notes: &[GraphSourceNote]) -> Vec<String> {
    duplicate_values(notes.iter().map(|note| note.note_id.as_str()))
}

fn duplicate_edge_ids(edges: &[GraphSourceEdge]) -> Vec<String> {
    duplicate_values(edges.iter().map(|edge| edge.edge_id.as_str()))
}

fn duplicate_values<'value>(values: impl Iterator<Item = &'value str>) -> Vec<String> {
    let mut counts = BTreeMap::<&str, usize>::new();
    for value in values {
        counts
            .entry(value)
            .and_modify(|count| *count = count.saturating_add(1))
            .or_insert(1);
    }
    counts
        .into_iter()
        .filter(|(_, count)| *count > 1)
        .map(|(value, _)| value.to_owned())
        .collect()
}

fn indexed_notes_by_id(notes: &[&GraphSourceNote]) -> BTreeMap<String, usize> {
    notes
        .iter()
        .enumerate()
        .map(|(index, note)| (note.note_id.as_str().to_owned(), index))
        .collect()
}

fn indexed_notes_by_path(notes: &[&GraphSourceNote]) -> BTreeMap<String, Vec<usize>> {
    let mut grouped = BTreeMap::<String, Vec<usize>>::new();
    for (index, note) in notes.iter().enumerate() {
        grouped
            .entry(canonical_path_key(note.relative_path.as_str()))
            .or_default()
            .push(index);
    }
    for values in grouped.values_mut() {
        values.sort_by(|left, right| {
            notes[*left]
                .relative_path
                .as_str()
                .cmp(notes[*right].relative_path.as_str())
        });
    }
    grouped
}

fn notes_by_link_name(notes: &[&GraphSourceNote]) -> BTreeMap<String, Vec<usize>> {
    let mut grouped = BTreeMap::<String, Vec<usize>>::new();
    for (index, note) in notes.iter().enumerate() {
        let mut names = BTreeSet::from([
            link_name(note.relative_path.as_str()),
            folded_trimmed(&note.title),
        ]);
        for alias in &note.aliases {
            let normalized = folded_trimmed(alias);
            if !normalized.is_empty() {
                names.insert(normalized);
            }
        }
        for name in names {
            if !name.is_empty() {
                grouped.entry(name).or_default().push(index);
            }
        }
    }
    for values in grouped.values_mut() {
        values.sort_by(|left, right| {
            notes[*left]
                .relative_path
                .as_str()
                .cmp(notes[*right].relative_path.as_str())
        });
    }
    grouped
}

fn nfc_normalized(value: &str) -> String {
    value.nfc().collect()
}

fn canonical_path_key(value: &str) -> String {
    nfc_normalized(&value.replace('\\', "/"))
}

fn folded_trimmed(value: &str) -> String {
    let normalized = nfc_normalized(value.trim());
    let folded = default_case_fold_str(&normalized);
    nfc_normalized(&folded)
}

fn link_name(path: &str) -> String {
    let canonical_path = canonical_path_key(path);
    folded_trimmed(posix_stem(&canonical_path))
}

fn posix_stem(path: &str) -> &str {
    let file_name = path.rsplit('/').next().unwrap_or(path);
    let Some(last_dot) = file_name.rfind('.') else {
        return file_name;
    };
    if last_dot == 0 || last_dot + 1 == file_name.len() {
        file_name
    } else {
        &file_name[..last_dot]
    }
}

fn projection_node(note: &GraphSourceNote) -> GraphProjectionNode {
    GraphProjectionNode {
        note_id: note.note_id.as_str().to_owned(),
        relative_path: note.relative_path.as_str().to_owned(),
        alexandria_type: note.alexandria_type.clone(),
        title: note.title.clone(),
        status: note.status.clone(),
        project: note.project.clone(),
    }
}

struct ProjectionEdgeResult {
    edges: Vec<GraphProjectionEdge>,
    issues: Vec<GraphProjectionIssue>,
}

fn projection_edges(
    edges: &[GraphSourceEdge],
    indexed_notes: &[&GraphSourceNote],
    notes_by_id: &BTreeMap<String, usize>,
    notes_by_path: &BTreeMap<String, Vec<usize>>,
    notes_by_link_name: &BTreeMap<String, Vec<usize>>,
) -> ProjectionEdgeResult {
    let mut projected = Vec::new();
    let mut issues = Vec::new();
    for edge in edges {
        let Some(source_index) = notes_by_id.get(&edge.source_note_id).copied() else {
            continue;
        };
        let source = indexed_notes[source_index];
        let resolution = resolve_target(
            edge,
            notes_by_id,
            notes_by_path,
            notes_by_link_name,
            indexed_notes,
        );
        let TargetResolution::Resolved(target) = resolution else {
            issues.push(target_issue(edge, resolution));
            continue;
        };
        projected.push(GraphProjectionEdge {
            edge_id: edge.edge_id.clone(),
            source_note_id: edge.source_note_id.clone(),
            source_path: source.relative_path.as_str().to_owned(),
            target_note_id: target.note_id.as_str().to_owned(),
            target_path: target.relative_path.as_str().to_owned(),
            relation: edge.relation.clone(),
            confidence: edge.confidence,
            source_kind: edge.source_kind.clone(),
        });
    }
    ProjectionEdgeResult {
        edges: projected,
        issues,
    }
}

#[derive(Clone, Copy)]
enum TargetResolution<'note> {
    Resolved(&'note GraphSourceNote),
    Missing,
    Ambiguous,
}

fn resolve_target<'note>(
    edge: &GraphSourceEdge,
    notes_by_id: &BTreeMap<String, usize>,
    notes_by_path: &BTreeMap<String, Vec<usize>>,
    notes_by_link_name: &BTreeMap<String, Vec<usize>>,
    notes: &[&'note GraphSourceNote],
) -> TargetResolution<'note> {
    if let Some(index) = edge
        .target_note_id
        .as_ref()
        .and_then(|note_id| notes_by_id.get(note_id).copied())
    {
        return TargetResolution::Resolved(notes[index]);
    }
    if let Some(candidates) = notes_by_path.get(&canonical_path_key(&edge.target_path)) {
        match candidates.as_slice() {
            [index] => return TargetResolution::Resolved(notes[*index]),
            [] => {}
            _ => return TargetResolution::Ambiguous,
        }
    }
    let mut resolution = TargetResolution::Missing;
    for candidate_name in candidate_link_names(&edge.target_path) {
        match notes_by_link_name.get(&candidate_name) {
            Some(candidates) if candidates.len() == 1 => {
                return TargetResolution::Resolved(notes[candidates[0]]);
            }
            Some(candidates) if candidates.len() > 1 => {
                resolution = TargetResolution::Ambiguous;
                break;
            }
            _ => {}
        }
    }
    resolution
}

fn candidate_link_names(path: &str) -> Vec<String> {
    let candidate = link_name(path);
    if candidate.is_empty() {
        Vec::new()
    } else {
        vec![candidate]
    }
}

fn target_issue(edge: &GraphSourceEdge, resolution: TargetResolution<'_>) -> GraphProjectionIssue {
    let ambiguous = matches!(resolution, TargetResolution::Ambiguous);
    GraphProjectionIssue {
        code: if ambiguous {
            GraphProjectionIssueCode::AmbiguousTargetNote
        } else {
            GraphProjectionIssueCode::MissingTargetNote
        },
        relative_path: edge.target_path.clone(),
        note_id: Some(edge.source_note_id.clone()),
        edge_id: Some(edge.edge_id.clone()),
        detail: if ambiguous {
            "edge target matches multiple healthy Obsidian notes".to_owned()
        } else {
            "edge target is absent from the healthy Obsidian index".to_owned()
        },
    }
}

fn index_error_issues(notes: &[GraphSourceNote]) -> Vec<GraphProjectionIssue> {
    notes
        .iter()
        .filter(|note| note.index_status == GraphIndexStatus::Error)
        .map(|note| GraphProjectionIssue {
            code: GraphProjectionIssueCode::IndexError,
            relative_path: note.relative_path.as_str().to_owned(),
            note_id: Some(note.note_id.as_str().to_owned()),
            edge_id: None,
            detail: "indexed note is in error state".to_owned(),
        })
        .collect()
}

fn issue_sort_key(left: &GraphProjectionIssue, right: &GraphProjectionIssue) -> std::cmp::Ordering {
    (
        left.code.as_str(),
        left.relative_path.as_str(),
        left.edge_id
            .as_deref()
            .or(left.note_id.as_deref())
            .unwrap_or(""),
    )
        .cmp(&(
            right.code.as_str(),
            right.relative_path.as_str(),
            right
                .edge_id
                .as_deref()
                .or(right.note_id.as_deref())
                .unwrap_or(""),
        ))
}

fn projection_batches(
    projection: &GraphProjection,
    batch_size: usize,
) -> Vec<GraphProjectionBatch> {
    let batch_count = batch_count(projection.nodes.len(), batch_size)
        .max(batch_count(projection.edges.len(), batch_size));
    (0..batch_count)
        .map(|batch_index| {
            let start = batch_index.saturating_mul(batch_size);
            let end = start.saturating_add(batch_size);
            GraphProjectionBatch {
                batch_index,
                projection: GraphProjection {
                    nodes: projection.nodes
                        [start.min(projection.nodes.len())..end.min(projection.nodes.len())]
                        .to_vec(),
                    edges: projection.edges
                        [start.min(projection.edges.len())..end.min(projection.edges.len())]
                        .to_vec(),
                },
            }
        })
        .collect()
}

fn batch_count(item_count: usize, batch_size: usize) -> usize {
    item_count.saturating_add(batch_size - 1) / batch_size
}

fn ambiguous_link_names(
    notes: &[&GraphSourceNote],
    grouped: &BTreeMap<String, Vec<usize>>,
) -> Vec<AmbiguousLinkName> {
    grouped
        .iter()
        .filter(|(_, candidates)| candidates.len() > 1)
        .map(|(name, candidates)| AmbiguousLinkName {
            normalized_name: name.clone(),
            candidate_paths: candidates
                .iter()
                .map(|index| notes[*index].relative_path.as_str().to_owned())
                .collect(),
        })
        .collect()
}
