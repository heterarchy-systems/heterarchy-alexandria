//! Python-baseline golden parity for deterministic document analysis.

use heterarchy_alexandria_core::document_analysis::{
    AnalysisErrorCode, DocumentBatch, DocumentId, DocumentInput, DocumentOutcome, FrontmatterEntry,
    FrontmatterScalar, FrontmatterValue, RelativeVaultPath, analyze_batch,
};
use serde::Deserialize;

const GOLDEN_CORPUS: &str = include_str!("../../../corpora/document_analysis/v1/cases.json");

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
    text: String,
    expected: GoldenExpected,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
enum GoldenExpected {
    Success {
        frontmatter: Vec<GoldenEntry>,
        body: String,
    },
    Error {
        error: GoldenError,
    },
}

#[derive(Debug, Deserialize)]
struct GoldenEntry {
    key: String,
    value: GoldenValue,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
enum GoldenValue {
    String(String),
    Integer(String),
    Float(String),
    Boolean(bool),
    Null,
    Sequence(Vec<GoldenScalar>),
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
enum GoldenScalar {
    String(String),
    Integer(String),
    Float(String),
    Boolean(bool),
    Null,
}

#[derive(Debug, Deserialize)]
struct GoldenError {
    code: String,
    message: String,
    recoverable: bool,
}

#[test]
fn document_analysis_matches_the_frozen_python_baseline() {
    let corpus: GoldenCorpus = match serde_json::from_str(GOLDEN_CORPUS) {
        Ok(value) => value,
        Err(error) => unreachable!("golden corpus must be valid JSON: {error}"),
    };
    assert_eq!(corpus.schema_version, 1);
    assert_eq!(corpus.feature, "document_analysis");

    let documents = corpus
        .cases
        .iter()
        .map(input_from_case)
        .collect::<Result<Vec<_>, _>>();
    let documents = match documents {
        Ok(value) => value,
        Err(error) => unreachable!("golden input must satisfy native bounds: {error}"),
    };
    let batch = match DocumentBatch::new(documents) {
        Ok(value) => value,
        Err(error) => unreachable!("golden batch must satisfy native bounds: {error}"),
    };
    let result = analyze_batch(batch);
    assert_eq!(result.results.len(), corpus.cases.len());

    for (case, outcome) in corpus.cases.iter().zip(&result.results) {
        compare_case(case, outcome);
    }
}

fn input_from_case(case: &GoldenCase) -> Result<DocumentInput, String> {
    let document_id = DocumentId::new(case.case_id.clone()).map_err(|error| error.to_string())?;
    let relative_path =
        RelativeVaultPath::new(case.relative_path.clone()).map_err(|error| error.to_string())?;
    DocumentInput::new(document_id, relative_path, case.text.clone())
        .map_err(|error| error.to_string())
}

fn compare_case(case: &GoldenCase, outcome: &DocumentOutcome) {
    match (&case.expected, outcome) {
        (
            GoldenExpected::Success { frontmatter, body },
            DocumentOutcome::Success {
                document_id,
                relative_path,
                analysis,
            },
        ) => {
            assert_eq!(document_id.as_str(), case.case_id);
            assert_eq!(relative_path.as_str(), case.relative_path);
            assert_eq!(&analysis.body, body, "body mismatch for {}", case.case_id);
            compare_frontmatter(&case.case_id, frontmatter, &analysis.frontmatter);
        }
        (
            GoldenExpected::Error { error: expected },
            DocumentOutcome::Error {
                document_id,
                relative_path,
                error: actual,
            },
        ) => {
            assert_eq!(document_id.as_str(), case.case_id);
            assert_eq!(relative_path.as_str(), case.relative_path);
            assert_eq!(expected.code, "FRONTMATTER_PARSE_ERROR");
            assert_eq!(actual.code, AnalysisErrorCode::FrontmatterParseError);
            assert_eq!(actual.message, expected.message);
            assert_eq!(actual.recoverable, expected.recoverable);
        }
        (GoldenExpected::Success { .. }, DocumentOutcome::Error { error, .. }) => {
            unreachable!(
                "{} unexpectedly failed native analysis: {}",
                case.case_id, error.message
            )
        }
        (GoldenExpected::Error { error, .. }, DocumentOutcome::Success { .. }) => {
            unreachable!(
                "{} unexpectedly succeeded; Python baseline failed with {}",
                case.case_id, error.message
            )
        }
    }
}

fn compare_frontmatter(case_id: &str, expected: &[GoldenEntry], actual: &[FrontmatterEntry]) {
    assert_eq!(actual.len(), expected.len(), "entry count for {case_id}");
    for (expected_entry, actual_entry) in expected.iter().zip(actual) {
        assert_eq!(
            actual_entry.key, expected_entry.key,
            "key order for {case_id}"
        );
        compare_value(case_id, &expected_entry.value, &actual_entry.value);
    }
}

fn compare_value(case_id: &str, expected: &GoldenValue, actual: &FrontmatterValue) {
    match (expected, actual) {
        (GoldenValue::String(left), FrontmatterValue::String(right)) => {
            assert_eq!(right, left, "string value for {case_id}");
        }
        (GoldenValue::Integer(left), FrontmatterValue::Integer(right)) => {
            compare_integer(case_id, left, right);
        }
        (GoldenValue::Float(left), FrontmatterValue::Float(right)) => {
            compare_float(case_id, left, right);
        }
        (GoldenValue::Boolean(left), FrontmatterValue::Boolean(right)) => {
            assert_eq!(right, left, "boolean value for {case_id}");
        }
        (GoldenValue::Null, FrontmatterValue::Null) => {}
        (GoldenValue::Sequence(left), FrontmatterValue::Sequence(right)) => {
            assert_eq!(right.len(), left.len(), "sequence length for {case_id}");
            for (expected_item, actual_item) in left.iter().zip(right) {
                compare_scalar(case_id, expected_item, actual_item);
            }
        }
        _ => unreachable!("frontmatter value kind mismatch for {case_id}"),
    }
}

fn compare_scalar(case_id: &str, expected: &GoldenScalar, actual: &FrontmatterScalar) {
    match (expected, actual) {
        (GoldenScalar::String(left), FrontmatterScalar::String(right)) => {
            assert_eq!(right, left, "sequence string for {case_id}");
        }
        (GoldenScalar::Integer(left), FrontmatterScalar::Integer(right)) => {
            compare_integer(case_id, left, right);
        }
        (GoldenScalar::Float(left), FrontmatterScalar::Float(right)) => {
            compare_float(case_id, left, right);
        }
        (GoldenScalar::Boolean(left), FrontmatterScalar::Boolean(right)) => {
            assert_eq!(right, left, "sequence boolean for {case_id}");
        }
        (GoldenScalar::Null, FrontmatterScalar::Null) => {}
        _ => unreachable!("frontmatter sequence kind mismatch for {case_id}"),
    }
}

fn compare_integer(case_id: &str, expected: &str, actual: &str) {
    let expected_value = expected.parse::<i128>();
    let actual_value = actual.parse::<i128>();
    match (expected_value, actual_value) {
        (Ok(left), Ok(right)) => assert_eq!(right, left, "integer value for {case_id}"),
        _ => unreachable!("golden corpus integer exceeds comparison bounds for {case_id}"),
    }
}

fn compare_float(case_id: &str, expected: &str, actual: &str) {
    let expected_value = expected.parse::<f64>();
    let actual_value = actual.parse::<f64>();
    match (expected_value, actual_value) {
        (Ok(left), Ok(right)) => {
            if left.is_infinite() || right.is_infinite() {
                assert!(
                    left.is_infinite()
                        && right.is_infinite()
                        && left.is_sign_positive() == right.is_sign_positive(),
                    "infinite float value for {case_id}"
                );
            } else {
                assert_eq!(right.to_bits(), left.to_bits(), "float value for {case_id}");
            }
        }
        _ => unreachable!("golden corpus float is invalid for {case_id}"),
    }
}
