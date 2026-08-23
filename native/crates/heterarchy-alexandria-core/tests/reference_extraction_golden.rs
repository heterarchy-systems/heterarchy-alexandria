//! Python-baseline golden parity for deterministic reference and edge extraction.

use heterarchy_alexandria_core::document_analysis::{DocumentId, RelativeVaultPath};
use heterarchy_alexandria_core::reference_extraction::{
    EdgeCandidate, EdgeSourceKind, FrontmatterEdgeInput, ReferenceBatch, ReferenceDocumentInput,
    extract_reference_batch,
};
use serde::Deserialize;

const GOLDEN_CORPUS: &str = include_str!("../../../corpora/link_extraction/v1/cases.json");

#[derive(Debug, Deserialize)]
struct GoldenCorpus {
    schema_version: u16,
    feature: String,
    cases: Vec<GoldenCase>,
}

#[derive(Debug, Deserialize)]
struct GoldenCase {
    case_id: String,
    note_id: String,
    relative_path: String,
    alexandria_root: String,
    body: String,
    frontmatter_edges: Vec<GoldenFrontmatterEdge>,
    expected_body_targets: Vec<String>,
    expected_edges: Vec<GoldenEdge>,
}

#[derive(Debug, Deserialize)]
struct GoldenFrontmatterEdge {
    target_path: Option<String>,
    target_note_id: Option<String>,
    relation: String,
    source_field: String,
}

#[derive(Debug, Deserialize)]
struct GoldenEdge {
    edge_id: String,
    source_note_id: String,
    source_path: String,
    target_note_id: Option<String>,
    target_path: String,
    relation: String,
    confidence: f64,
    source_kind: String,
    identity_material: String,
}

#[test]
fn reference_extraction_matches_the_frozen_python_graph_baseline() {
    let corpus: GoldenCorpus = match serde_json::from_str(GOLDEN_CORPUS) {
        Ok(value) => value,
        Err(error) => unreachable!("reference corpus must be valid JSON: {error}"),
    };
    assert_eq!(corpus.schema_version, 1);
    assert_eq!(corpus.feature, "link_extraction");

    let documents = corpus
        .cases
        .iter()
        .map(input_from_case)
        .collect::<Result<Vec<_>, _>>();
    let documents = match documents {
        Ok(value) => value,
        Err(error) => unreachable!("golden reference input must be valid: {error}"),
    };
    let batch = match ReferenceBatch::new(documents) {
        Ok(value) => value,
        Err(error) => unreachable!("golden reference batch must be valid: {error}"),
    };
    let result = match extract_reference_batch(batch) {
        Ok(value) => value,
        Err(error) => unreachable!("canonical reference extraction failed: {error}"),
    };
    assert_eq!(result.results.len(), corpus.cases.len());

    for (case, actual) in corpus.cases.iter().zip(&result.results) {
        assert_eq!(actual.note_id.as_str(), case.note_id);
        assert_eq!(actual.relative_path.as_str(), case.relative_path);
        let accepted_targets = actual
            .references
            .iter()
            .filter_map(|reference| reference.normalized_target_path.clone())
            .collect::<Vec<_>>();
        assert_eq!(
            accepted_targets, case.expected_body_targets,
            "{} normalized body target order",
            case.case_id
        );
        assert_eq!(
            actual.edges.len(),
            case.expected_edges.len(),
            "{} edge count",
            case.case_id
        );
        for (expected_edge, actual_edge) in case.expected_edges.iter().zip(&actual.edges) {
            compare_edge(&case.case_id, expected_edge, actual_edge);
        }
        validate_reference_ranges(case, actual);
    }
}

fn input_from_case(case: &GoldenCase) -> Result<ReferenceDocumentInput, String> {
    let note_id = DocumentId::new(case.note_id.clone()).map_err(|error| error.to_string())?;
    let relative_path =
        RelativeVaultPath::new(case.relative_path.clone()).map_err(|error| error.to_string())?;
    let frontmatter_edges = case
        .frontmatter_edges
        .iter()
        .map(|edge| {
            FrontmatterEdgeInput::new(
                edge.target_path.clone(),
                edge.target_note_id.clone(),
                edge.relation.clone(),
                edge.source_field.clone(),
            )
            .map_err(|error| error.to_string())
        })
        .collect::<Result<Vec<_>, _>>()?;
    ReferenceDocumentInput::new(
        note_id,
        relative_path,
        case.alexandria_root.clone(),
        case.body.clone(),
        frontmatter_edges,
    )
    .map_err(|error| error.to_string())
}

fn compare_edge(case_id: &str, expected: &GoldenEdge, actual: &EdgeCandidate) {
    assert_eq!(
        actual.source_note_id, expected.source_note_id,
        "{case_id} source id"
    );
    assert_eq!(
        actual.source_path, expected.source_path,
        "{case_id} source path"
    );
    assert_eq!(
        actual.target_note_id, expected.target_note_id,
        "{case_id} target id"
    );
    assert_eq!(
        actual.target_path, expected.target_path,
        "{case_id} target path"
    );
    assert_eq!(actual.relation, expected.relation, "{case_id} relation");
    assert_eq!(actual.confidence.to_bits(), expected.confidence.to_bits());
    let actual_source_kind = match actual.source_kind {
        EdgeSourceKind::Frontmatter => "frontmatter",
        EdgeSourceKind::Wikilink => "wikilink",
    };
    assert_eq!(
        actual_source_kind, expected.source_kind,
        "{case_id} source kind"
    );
    assert_eq!(actual.edge_id, expected.edge_id, "{case_id} edge id");
    assert_eq!(
        actual.identity_material, expected.identity_material,
        "{case_id} edge identity material"
    );
    assert_eq!(
        expected.edge_id.len(),
        64,
        "{case_id} baseline SHA-256 length"
    );
}

fn validate_reference_ranges(
    case: &GoldenCase,
    actual: &heterarchy_alexandria_core::reference_extraction::ReferenceDocumentResult,
) {
    let mut previous_start = 0_usize;
    for reference in &actual.references {
        let range = reference.source_range;
        assert!(
            range.byte_start <= range.byte_end,
            "{} byte range",
            case.case_id
        );
        assert!(
            range.byte_end <= case.body.len(),
            "{} byte range end",
            case.case_id
        );
        assert!(case.body.is_char_boundary(range.byte_start));
        assert!(case.body.is_char_boundary(range.byte_end));
        assert!(
            range.byte_start >= previous_start,
            "{} source order",
            case.case_id
        );
        assert_eq!(
            &case.body[range.byte_start..range.byte_end],
            reference.raw_syntax,
            "{} raw source slice",
            case.case_id
        );
        assert_eq!(
            case.body[..range.byte_start].chars().count(),
            range.char_start,
            "{} character start",
            case.case_id
        );
        assert_eq!(
            case.body[range.byte_start..range.byte_end].chars().count(),
            range.char_end - range.char_start,
            "{} character length",
            case.case_id
        );
        previous_start = range.byte_start;
    }
}
