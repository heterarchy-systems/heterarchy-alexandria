//! Lower-copy `PyO3` boundary for raw Markdown integrity scanning.
//!
//! The JSON wire remains a parity/debug contract. Production can pass Python strings directly and
//! receive only document indices, stable warning ordinals, and optional field names.

use std::collections::BTreeSet;

use heterarchy_alexandria_core::document_analysis::RelativeVaultPath;
use heterarchy_alexandria_core::document_integrity::{
    RawIntegrityBatch, RawIntegrityDocumentInput, RawIntegrityFindingCode, scan_raw_integrity_batch,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;

pub(crate) type CompactRawIntegrityFinding = (usize, u8, Option<String>);

#[pyfunction]
pub(crate) fn scan_raw_data_integrity_compact(
    python: Python<'_>,
    documents: Vec<(PyBackedStr, PyBackedStr)>,
    collection_fields: Vec<PyBackedStr>,
    boolean_fields: Vec<PyBackedStr>,
    unrecoverable_redacted_url_pattern: PyBackedStr,
) -> PyResult<Vec<CompactRawIntegrityFinding>> {
    python
        .detach(move || {
            let inputs = documents
                .into_iter()
                .map(|(relative_path, text)| {
                    let path = RelativeVaultPath::new(relative_path.to_string())
                        .map_err(|error| error.to_string())?;
                    RawIntegrityDocumentInput::new(path, text.to_string())
                        .map_err(|error| error.to_string())
                })
                .collect::<Result<Vec<_>, String>>()?;
            let batch = RawIntegrityBatch::new(
                collection_fields
                    .into_iter()
                    .map(|field| field.to_string())
                    .collect::<BTreeSet<_>>(),
                boolean_fields
                    .into_iter()
                    .map(|field| field.to_string())
                    .collect::<BTreeSet<_>>(),
                unrecoverable_redacted_url_pattern.as_ref(),
                inputs,
            )
            .map_err(|error| error.to_string())?;
            let result = scan_raw_integrity_batch(batch);
            Ok(result
                .results
                .into_iter()
                .enumerate()
                .flat_map(|(document_index, result)| {
                    result.findings.into_iter().map(move |finding| {
                        (
                            document_index,
                            finding_code(finding.code),
                            finding.field_name,
                        )
                    })
                })
                .collect())
        })
        .map_err(|error: String| {
            PyValueError::new_err(format!("NATIVE_RAW_DATA_INTEGRITY_INPUT_ERROR: {error}"))
        })
}

const fn finding_code(code: RawIntegrityFindingCode) -> u8 {
    match code {
        RawIntegrityFindingCode::LegacyTupleCollection => 0,
        RawIntegrityFindingCode::EmptyCollectionScalar => 1,
        RawIntegrityFindingCode::InvalidCollectionType => 2,
        RawIntegrityFindingCode::StringBoolean => 3,
        RawIntegrityFindingCode::InvalidBooleanValue => 4,
        RawIntegrityFindingCode::UnrecoverableRedactedUrl => 5,
    }
}

#[cfg(test)]
mod tests {
    use super::finding_code;
    use heterarchy_alexandria_core::document_integrity::RawIntegrityFindingCode;

    #[test]
    fn compact_warning_ordinals_are_stable() {
        assert_eq!(
            finding_code(RawIntegrityFindingCode::LegacyTupleCollection),
            0
        );
        assert_eq!(
            finding_code(RawIntegrityFindingCode::EmptyCollectionScalar),
            1
        );
        assert_eq!(
            finding_code(RawIntegrityFindingCode::InvalidCollectionType),
            2
        );
        assert_eq!(finding_code(RawIntegrityFindingCode::StringBoolean), 3);
        assert_eq!(
            finding_code(RawIntegrityFindingCode::InvalidBooleanValue),
            4
        );
        assert_eq!(
            finding_code(RawIntegrityFindingCode::UnrecoverableRedactedUrl),
            5
        );
    }
}
