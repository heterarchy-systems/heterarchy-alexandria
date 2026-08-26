use std::collections::{BTreeMap, BTreeSet};

use heterarchy_alexandria_core::document_analysis::RelativeVaultPath;
use heterarchy_alexandria_core::document_integrity::{
    RawIntegrityBatch, RawIntegrityDocumentInput, RawIntegrityFindingCode, scan_raw_integrity_batch,
};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct GoldenCorpus {
    collection_fields: Vec<String>,
    boolean_fields: Vec<String>,
    unrecoverable_redacted_url_pattern: String,
    cases: Vec<GoldenCase>,
}

#[derive(Debug, Deserialize)]
struct GoldenCase {
    name: String,
    markdown: String,
    expected: Vec<ExpectedWarning>,
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
struct ExpectedWarning {
    code: String,
    count: usize,
    fields: Vec<String>,
}

fn warning_code(code: RawIntegrityFindingCode) -> String {
    serde_json::to_value(code)
        .ok()
        .and_then(|value| value.as_str().map(str::to_owned))
        .unwrap_or_else(|| unreachable!("finding code must serialize as a string"))
}

fn aggregate_findings(
    findings: &[heterarchy_alexandria_core::document_integrity::RawIntegrityFinding],
) -> Vec<ExpectedWarning> {
    let mut aggregated: BTreeMap<String, (usize, BTreeSet<String>)> = BTreeMap::new();
    for finding in findings {
        let entry = aggregated
            .entry(warning_code(finding.code))
            .or_insert_with(|| (0, BTreeSet::new()));
        entry.0 += 1;
        if let Some(field_name) = finding.field_name.as_ref() {
            entry.1.insert(field_name.clone());
        }
    }
    let preferred_order = [
        "LEGACY_TUPLE_COLLECTION",
        "EMPTY_COLLECTION_SCALAR",
        "INVALID_COLLECTION_TYPE",
        "STRING_BOOLEAN",
        "INVALID_BOOLEAN_VALUE",
        "UNRECOVERABLE_REDACTED_URL",
    ];
    preferred_order
        .into_iter()
        .filter_map(|code| {
            aggregated
                .remove(code)
                .map(|(count, fields)| ExpectedWarning {
                    code: code.to_owned(),
                    count,
                    fields: fields.into_iter().collect(),
                })
        })
        .collect()
}

#[test]
fn raw_data_integrity_matches_frozen_python_warning_semantics() {
    let corpus: GoldenCorpus = serde_json::from_str(include_str!(
        "../../../golden/raw_data_integrity_cases.json"
    ))
    .unwrap_or_else(|error| unreachable!("golden corpus must be valid JSON: {error}"));

    for case in corpus.cases {
        let relative_path = RelativeVaultPath::new(format!("cases/{}.md", case.name))
            .unwrap_or_else(|error| unreachable!("golden path must be valid: {error}"));
        let document = RawIntegrityDocumentInput::new(relative_path, case.markdown)
            .unwrap_or_else(|error| unreachable!("golden document must be valid: {error}"));
        let batch = RawIntegrityBatch::new(
            corpus.collection_fields.iter().cloned().collect(),
            corpus.boolean_fields.iter().cloned().collect(),
            &corpus.unrecoverable_redacted_url_pattern,
            vec![document],
        )
        .unwrap_or_else(|error| unreachable!("golden batch must be valid: {error}"));
        let result = scan_raw_integrity_batch(batch);
        assert_eq!(result.results.len(), 1, "case={}", case.name);
        assert_eq!(
            aggregate_findings(&result.results[0].findings),
            case.expected,
            "case={}",
            case.name
        );
    }
}
