//! Python-baseline golden parity for deterministic Markdown chunking.

use heterarchy_alexandria_core::document_analysis::{DocumentId, RelativeVaultPath};
use heterarchy_alexandria_core::markdown_chunking::{
    ChunkBatch, ChunkDocumentInput, ChunkDocumentOutcome, ChunkPolicy, ChunkRecord,
    ChunkSourceKind, chunk_batch,
};
use serde::Deserialize;

const GOLDEN_CORPUS: &str = include_str!("../../../corpora/chunking/v1/cases.json");

#[derive(Debug, Deserialize)]
struct GoldenCorpus {
    schema_version: u16,
    feature: String,
    cases: Vec<GoldenCase>,
}

#[derive(Debug, Deserialize)]
struct GoldenCase {
    case_id: String,
    relative_path: String,
    title: String,
    content: String,
    max_chars: usize,
    overlap_chars: usize,
    expected: Vec<GoldenChunk>,
}

#[derive(Debug, Deserialize)]
struct GoldenChunk {
    chunk_index: usize,
    heading: Option<String>,
    content: String,
}

#[test]
fn markdown_chunking_matches_the_frozen_python_baseline() {
    let corpus: GoldenCorpus = match serde_json::from_str(GOLDEN_CORPUS) {
        Ok(value) => value,
        Err(error) => unreachable!("chunking corpus must be valid JSON: {error}"),
    };
    assert_eq!(corpus.schema_version, 1);
    assert_eq!(corpus.feature, "chunking");

    for case in &corpus.cases {
        let chunks = run_case(case);
        assert_eq!(
            chunks.len(),
            case.expected.len(),
            "{} chunk count",
            case.case_id
        );
        for (expected, actual) in case.expected.iter().zip(&chunks) {
            assert_eq!(
                actual.chunk_index, expected.chunk_index,
                "{} index",
                case.case_id
            );
            assert_eq!(actual.heading, expected.heading, "{} heading", case.case_id);
            assert_eq!(actual.content, expected.content, "{} content", case.case_id);
            validate_source_range(case, actual);
            validate_heading_path(case, actual);
        }
    }
}

fn run_case(case: &GoldenCase) -> Vec<ChunkRecord> {
    let document_id = match DocumentId::new(case.case_id.clone()) {
        Ok(value) => value,
        Err(error) => unreachable!("valid golden identity rejected: {error}"),
    };
    let relative_path = match RelativeVaultPath::new(case.relative_path.clone()) {
        Ok(value) => value,
        Err(error) => unreachable!("valid golden path rejected: {error}"),
    };
    let document = match ChunkDocumentInput::new(
        document_id,
        relative_path,
        case.title.clone(),
        case.content.clone(),
    ) {
        Ok(value) => value,
        Err(error) => unreachable!("valid golden document rejected: {error}"),
    };
    let policy = match ChunkPolicy::new(case.max_chars, case.overlap_chars) {
        Ok(value) => value,
        Err(error) => unreachable!("valid golden policy rejected: {error}"),
    };
    let batch = match ChunkBatch::new(policy, vec![document]) {
        Ok(value) => value,
        Err(error) => unreachable!("valid golden batch rejected: {error}"),
    };
    let result = match chunk_batch(batch) {
        Ok(value) => value,
        Err(error) => unreachable!("canonical heading regex failed: {error}"),
    };
    let mut outcomes = result.results.into_iter();
    let outcome = outcomes.next();
    assert!(outcomes.next().is_none());
    match outcome {
        Some(ChunkDocumentOutcome::Success {
            document_id,
            relative_path,
            chunks,
        }) => {
            assert_eq!(document_id.as_str(), case.case_id);
            assert_eq!(relative_path.as_str(), case.relative_path);
            chunks
        }
        Some(ChunkDocumentOutcome::Error { error, .. }) => {
            unreachable!("{} unexpectedly failed: {}", case.case_id, error.message)
        }
        None => unreachable!("one golden input must produce one outcome"),
    }
}

fn validate_source_range(case: &GoldenCase, chunk: &ChunkRecord) {
    let source = match chunk.source_kind {
        ChunkSourceKind::Content => &case.content,
        ChunkSourceKind::TitleFallback => &case.title,
    };
    assert!(chunk.source_range.byte_start <= chunk.source_range.byte_end);
    assert!(chunk.source_range.byte_end <= source.len());
    assert!(source.is_char_boundary(chunk.source_range.byte_start));
    assert!(source.is_char_boundary(chunk.source_range.byte_end));
    let selected = &source[chunk.source_range.byte_start..chunk.source_range.byte_end];
    assert_eq!(selected, chunk.content, "{} source slice", case.case_id);
    assert_eq!(
        source[..chunk.source_range.byte_start].chars().count(),
        chunk.source_range.char_start,
        "{} character start",
        case.case_id
    );
    assert_eq!(
        selected.chars().count(),
        chunk.source_range.char_end - chunk.source_range.char_start,
        "{} character length",
        case.case_id
    );
}

fn validate_heading_path(case: &GoldenCase, chunk: &ChunkRecord) {
    if let Some(heading) = &chunk.heading
        && !chunk.heading_path.is_empty()
    {
        assert_eq!(
            chunk.heading_path.last(),
            Some(heading),
            "{} heading path leaf",
            case.case_id
        );
    }
}
