//! `PyO3` wire conversion for raw Markdown/frontmatter integrity scanning.

use std::collections::BTreeSet;

use heterarchy_alexandria_core::document_analysis::RelativeVaultPath;
use heterarchy_alexandria_core::document_integrity::{
    RAW_DATA_INTEGRITY_VERSION, RawIntegrityBatch, RawIntegrityDocumentInput,
    scan_raw_integrity_batch,
};
use serde::Deserialize;

use crate::validate_contract_version;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawIntegrityBatchWire {
    contract_version: u16,
    raw_integrity_version: u16,
    collection_fields: Vec<String>,
    boolean_fields: Vec<String>,
    unrecoverable_redacted_url_pattern: String,
    documents: Vec<RawIntegrityDocumentWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawIntegrityDocumentWire {
    relative_path: String,
    text: String,
}

pub(crate) fn scan_raw_data_integrity_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: RawIntegrityBatchWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_RAW_DATA_INTEGRITY_INPUT_ERROR: {error}"))?;
    validate_contract_version(
        wire.contract_version,
        "NATIVE_RAW_DATA_INTEGRITY_CONTRACT_ERROR",
    )?;
    if wire.raw_integrity_version != RAW_DATA_INTEGRITY_VERSION {
        return Err(format!(
            "NATIVE_RAW_DATA_INTEGRITY_CONTRACT_ERROR: expected raw integrity version {RAW_DATA_INTEGRITY_VERSION}, found {}",
            wire.raw_integrity_version
        ));
    }
    let documents = wire
        .documents
        .into_iter()
        .map(document_from_wire)
        .collect::<Result<Vec<_>, _>>()?;
    let batch = RawIntegrityBatch::new(
        wire.collection_fields.into_iter().collect::<BTreeSet<_>>(),
        wire.boolean_fields.into_iter().collect::<BTreeSet<_>>(),
        &wire.unrecoverable_redacted_url_pattern,
        documents,
    )
    .map_err(|error| format!("NATIVE_RAW_DATA_INTEGRITY_INPUT_ERROR: {error}"))?;
    serde_json::to_vec(&scan_raw_integrity_batch(batch))
        .map_err(|error| format!("NATIVE_RAW_DATA_INTEGRITY_OUTPUT_ERROR: {error}"))
}

fn document_from_wire(wire: RawIntegrityDocumentWire) -> Result<RawIntegrityDocumentInput, String> {
    let relative_path = RelativeVaultPath::new(wire.relative_path)
        .map_err(|error| format!("NATIVE_RAW_DATA_INTEGRITY_INPUT_ERROR: {error}"))?;
    RawIntegrityDocumentInput::new(relative_path, wire.text)
        .map_err(|error| format!("NATIVE_RAW_DATA_INTEGRITY_INPUT_ERROR: {error}"))
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::scan_raw_data_integrity_payload;

    #[test]
    fn wire_rejects_unknown_fields_fail_closed() {
        let payload = br#"{
            "contract_version": 1,
            "raw_integrity_version": 1,
            "collection_fields": ["tags"],
            "boolean_fields": ["source_of_truth"],
            "unrecoverable_redacted_url_pattern": "https?://<REDACTED_LONG_VALUE>",
            "documents": [],
            "unexpected": true
        }"#;
        let error = match scan_raw_data_integrity_payload(payload) {
            Ok(_) => String::new(),
            Err(error) => error,
        };
        assert!(
            error.starts_with("NATIVE_RAW_DATA_INTEGRITY_INPUT_ERROR:"),
            "unknown wire fields must be rejected fail-closed",
        );
    }

    #[test]
    fn wire_runs_one_coarse_raw_integrity_batch() {
        let payload = br#"{
            "contract_version": 1,
            "raw_integrity_version": 1,
            "collection_fields": ["tags"],
            "boolean_fields": ["source_of_truth"],
            "unrecoverable_redacted_url_pattern": "https?://<REDACTED_LONG_VALUE>",
            "documents": [
                {
                    "relative_path": "Contexts/Legacy.md",
                    "text": "---\ntags: \"('alpha', 'beta')\"\nsource_of_truth: \"true\"\n---\nBody\n"
                }
            ]
        }"#;
        let encoded = scan_raw_data_integrity_payload(payload)
            .unwrap_or_else(|error| unreachable!("valid raw-integrity payload failed: {error}"));
        let decoded: Value = serde_json::from_slice(&encoded)
            .unwrap_or_else(|error| unreachable!("adapter emitted invalid JSON: {error}"));
        assert_eq!(decoded["contract_version"], 1);
        assert_eq!(decoded["raw_integrity_version"], 1);
        assert_eq!(
            decoded["results"][0]["findings"][0]["code"],
            "LEGACY_TUPLE_COLLECTION"
        );
        assert_eq!(
            decoded["results"][0]["findings"][1]["code"],
            "STRING_BOOLEAN"
        );
    }
}
