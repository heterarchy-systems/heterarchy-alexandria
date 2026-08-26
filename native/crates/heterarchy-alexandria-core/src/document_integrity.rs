//! Deterministic raw Markdown/frontmatter integrity analysis.
//!
//! Python owns filesystem inventory, I/O, readiness policy, and repair effects. This module
//! only inspects already-read Markdown text using caller-provided metadata field policy.

use regex::Regex;
use serde::Serialize;
use std::borrow::Cow;
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::{Display, Formatter};

use crate::ComputeContractVersion;
use crate::document_analysis::RelativeVaultPath;

/// Version of the raw data-integrity result contract.
pub const RAW_DATA_INTEGRITY_VERSION: u16 = 1;

const MAX_DOCUMENTS_PER_BATCH: usize = 4_096;
const MAX_DOCUMENT_BYTES: usize = 16 * 1024 * 1024;
const MAX_BATCH_BYTES: usize = 128 * 1024 * 1024;

/// One already-read Markdown document submitted for raw representation inspection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawIntegrityDocumentInput {
    relative_path: RelativeVaultPath,
    text: String,
}

impl RawIntegrityDocumentInput {
    /// Create one bounded document input without taking filesystem authority from Python.
    ///
    /// # Errors
    ///
    /// Returns an error when the document exceeds the bounded native input size.
    pub fn new(relative_path: RelativeVaultPath, text: String) -> Result<Self, RawIntegrityError> {
        if text.len() > MAX_DOCUMENT_BYTES {
            return Err(RawIntegrityError::new(format!(
                "document {} exceeds the {} byte raw integrity limit",
                relative_path.as_str(),
                MAX_DOCUMENT_BYTES
            )));
        }
        Ok(Self {
            relative_path,
            text,
        })
    }
}

/// Validated raw-integrity field policy reusable across borrowed document batches.
pub struct RawIntegrityPolicy {
    collection_fields: BTreeSet<String>,
    boolean_fields: BTreeSet<String>,
    unrecoverable_redacted_url: Regex,
}

impl RawIntegrityPolicy {
    /// Validate field identities and compile the caller-owned redacted-URL expression once.
    ///
    /// # Errors
    ///
    /// Returns an error for blank/null field names or invalid regex syntax.
    pub fn new(
        collection_fields: BTreeSet<String>,
        boolean_fields: BTreeSet<String>,
        unrecoverable_redacted_url_pattern: &str,
    ) -> Result<Self, RawIntegrityError> {
        validate_field_set("collection_fields", &collection_fields)?;
        validate_field_set("boolean_fields", &boolean_fields)?;
        let unrecoverable_redacted_url =
            Regex::new(unrecoverable_redacted_url_pattern).map_err(|error| {
                RawIntegrityError::new(format!("invalid redacted URL regex: {error}"))
            })?;
        Ok(Self {
            collection_fields,
            boolean_fields,
            unrecoverable_redacted_url,
        })
    }
}

/// Coarse-grained policy and owned Markdown batch supplied by JSON/debug adapters.
pub struct RawIntegrityBatch {
    policy: RawIntegrityPolicy,
    documents: Vec<RawIntegrityDocumentInput>,
}

impl RawIntegrityBatch {
    /// Validate the configured field policy, redacted-URL expression, and batch bounds.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid field identities, regex syntax, or bounded-input overflow.
    pub fn new(
        collection_fields: BTreeSet<String>,
        boolean_fields: BTreeSet<String>,
        unrecoverable_redacted_url_pattern: &str,
        documents: Vec<RawIntegrityDocumentInput>,
    ) -> Result<Self, RawIntegrityError> {
        let policy = RawIntegrityPolicy::new(
            collection_fields,
            boolean_fields,
            unrecoverable_redacted_url_pattern,
        )?;
        if documents.len() > MAX_DOCUMENTS_PER_BATCH {
            return Err(RawIntegrityError::new(format!(
                "raw integrity batch exceeds the {MAX_DOCUMENTS_PER_BATCH} item limit"
            )));
        }
        let total_bytes = documents.iter().try_fold(0_usize, |total, document| {
            total
                .checked_add(document.text.len())
                .ok_or_else(|| RawIntegrityError::new("raw integrity batch byte count overflow"))
        })?;
        if total_bytes > MAX_BATCH_BYTES {
            return Err(RawIntegrityError::new(format!(
                "raw integrity batch exceeds the {MAX_BATCH_BYTES} byte limit"
            )));
        }
        Ok(Self { policy, documents })
    }
}

fn validate_field_set(name: &str, fields: &BTreeSet<String>) -> Result<(), RawIntegrityError> {
    if fields.iter().any(|field| field.trim().is_empty()) {
        return Err(RawIntegrityError::new(format!(
            "{name} must not contain blank field names"
        )));
    }
    if fields.iter().any(|field| field.contains('\0')) {
        return Err(RawIntegrityError::new(format!(
            "{name} must not contain null bytes"
        )));
    }
    Ok(())
}

/// Invalid batch input rejected before raw integrity compute runs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawIntegrityError {
    message: String,
}

impl RawIntegrityError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for RawIntegrityError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for RawIntegrityError {}

/// Stable warning categories matching the existing Python operational scanner contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RawIntegrityFindingCode {
    /// Python tuple syntax was stored where YAML string collections are canonical.
    LegacyTupleCollection,
    /// A collection field was present with neither a scalar nor block-list items.
    EmptyCollectionScalar,
    /// A collection field used a non-string or otherwise unsupported representation.
    InvalidCollectionType,
    /// A boolean was quoted and therefore persisted as a string scalar.
    StringBoolean,
    /// A configured boolean field did not contain true/false semantics.
    InvalidBooleanValue,
    /// Markdown contains a configured unrecoverable redacted URL marker.
    UnrecoverableRedactedUrl,
}

/// One deterministic raw-representation finding.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RawIntegrityFinding {
    /// Stable warning code.
    pub code: RawIntegrityFindingCode,
    /// Top-level frontmatter field when the finding is field-scoped.
    pub field_name: Option<String>,
}

/// Findings for one caller-owned Markdown path.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RawIntegrityDocumentResult {
    /// Caller-provided vault-relative path.
    pub relative_path: RelativeVaultPath,
    /// Deterministically ordered findings for this document.
    pub findings: Vec<RawIntegrityFinding>,
}

/// Coarse result returned from one native batch call.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RawIntegrityBatchResult {
    /// Python/Rust compute contract version.
    pub contract_version: u16,
    /// Raw integrity schema/algorithm version.
    pub raw_integrity_version: u16,
    /// Per-document findings in request order.
    pub results: Vec<RawIntegrityDocumentResult>,
}

/// Inspect an owned JSON/debug batch without filesystem access or mutation.
#[must_use]
pub fn scan_raw_integrity_batch(batch: RawIntegrityBatch) -> RawIntegrityBatchResult {
    let RawIntegrityBatch { policy, documents } = batch;
    let results = documents
        .into_iter()
        .map(|document| RawIntegrityDocumentResult {
            relative_path: document.relative_path,
            findings: scan_raw_integrity_text(&document.text, &policy),
        })
        .collect();
    RawIntegrityBatchResult {
        contract_version: ComputeContractVersion::CURRENT.value(),
        raw_integrity_version: RAW_DATA_INTEGRITY_VERSION,
        results,
    }
}

/// Validate and inspect borrowed Markdown documents without cloning their text.
///
/// The returned tuples use request-order document indices so adapters can keep Python-owned paths.
///
/// # Errors
///
/// Returns an error when document cardinality/bytes/path identity exceed the native contract.
pub fn scan_raw_integrity_borrowed_batch<'text>(
    policy: &RawIntegrityPolicy,
    documents: &[(&'text str, &'text str)],
) -> Result<Vec<(usize, RawIntegrityFinding)>, RawIntegrityError> {
    if documents.len() > MAX_DOCUMENTS_PER_BATCH {
        return Err(RawIntegrityError::new(format!(
            "raw integrity batch exceeds the {MAX_DOCUMENTS_PER_BATCH} item limit"
        )));
    }
    let mut total_bytes = 0_usize;
    for (relative_path, text) in documents {
        validate_borrowed_path(relative_path)?;
        if text.len() > MAX_DOCUMENT_BYTES {
            return Err(RawIntegrityError::new(format!(
                "document {relative_path} exceeds the {MAX_DOCUMENT_BYTES} byte raw integrity limit"
            )));
        }
        total_bytes = total_bytes
            .checked_add(text.len())
            .ok_or_else(|| RawIntegrityError::new("raw integrity batch byte count overflow"))?;
    }
    if total_bytes > MAX_BATCH_BYTES {
        return Err(RawIntegrityError::new(format!(
            "raw integrity batch exceeds the {MAX_BATCH_BYTES} byte limit"
        )));
    }
    Ok(documents
        .iter()
        .enumerate()
        .flat_map(|(document_index, (_, text))| {
            scan_raw_integrity_text(text, policy)
                .into_iter()
                .map(move |finding| (document_index, finding))
        })
        .collect())
}

fn validate_borrowed_path(value: &str) -> Result<(), RawIntegrityError> {
    if value.trim().is_empty() {
        return Err(RawIntegrityError::new("relative_path must not be blank"));
    }
    if value.contains('\0') {
        return Err(RawIntegrityError::new(
            "relative_path must not contain a null byte",
        ));
    }
    Ok(())
}

fn scan_raw_integrity_text(text: &str, policy: &RawIntegrityPolicy) -> Vec<RawIntegrityFinding> {
    let fields = top_level_frontmatter_values(text);
    let mut findings = Vec::new();

    for field_name in &policy.collection_fields {
        let Some(raw_field) = fields.get(field_name) else {
            continue;
        };
        if is_yaml_collection(raw_field) {
            continue;
        }
        let code = if is_legacy_tuple_collection(&raw_field.value) {
            RawIntegrityFindingCode::LegacyTupleCollection
        } else if raw_field.value.is_empty() && raw_field.list_items.is_empty() {
            RawIntegrityFindingCode::EmptyCollectionScalar
        } else {
            RawIntegrityFindingCode::InvalidCollectionType
        };
        findings.push(RawIntegrityFinding {
            code,
            field_name: Some(field_name.clone()),
        });
    }

    for field_name in &policy.boolean_fields {
        let Some(raw_field) = fields.get(field_name) else {
            continue;
        };
        if let Some(code) = boolean_warning_code(&raw_field.value) {
            findings.push(RawIntegrityFinding {
                code,
                field_name: Some(field_name.clone()),
            });
        }
    }

    if policy.unrecoverable_redacted_url.is_match(text) {
        findings.push(RawIntegrityFinding {
            code: RawIntegrityFindingCode::UnrecoverableRedactedUrl,
            field_name: None,
        });
    }
    findings.sort_by(|left, right| {
        left.code
            .cmp(&right.code)
            .then_with(|| left.field_name.cmp(&right.field_name))
    });
    findings
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RawFrontmatterField {
    value: String,
    list_items: Vec<String>,
}

fn top_level_frontmatter_values(markdown: &str) -> BTreeMap<String, RawFrontmatterField> {
    let mut lines = LogicalLineIter::new(markdown);
    if lines.next().is_none_or(|line| line.trim() != "---") {
        return BTreeMap::new();
    }
    let mut values: BTreeMap<String, RawFrontmatterField> = BTreeMap::new();
    let mut active_list_key: Option<String> = None;
    for line in lines {
        if line.trim() == "---" {
            break;
        }
        if let Some(active_key) = active_list_key.as_ref()
            && line.trim().starts_with('-')
        {
            if let Some(field) = values.get_mut(active_key) {
                field
                    .list_items
                    .push(line.trim().trim_start_matches('-').trim().to_owned());
            }
            continue;
        }
        if line != line.trim_start() || !line.contains(':') {
            continue;
        }
        active_list_key = None;
        let Some((key, raw_value)) = line.split_once(':') else {
            continue;
        };
        let normalized_key = key.trim();
        if normalized_key.is_empty() {
            continue;
        }
        let value = raw_value.trim().to_owned();
        values.insert(
            normalized_key.to_owned(),
            RawFrontmatterField {
                value: value.clone(),
                list_items: Vec::new(),
            },
        );
        if value.is_empty() {
            active_list_key = Some(normalized_key.to_owned());
        }
    }
    values
}

struct LogicalLineIter<'text> {
    markdown: &'text str,
    cursor: usize,
}

impl<'text> LogicalLineIter<'text> {
    const fn new(markdown: &'text str) -> Self {
        Self {
            markdown,
            cursor: 0,
        }
    }
}

impl<'text> Iterator for LogicalLineIter<'text> {
    type Item = &'text str;

    fn next(&mut self) -> Option<Self::Item> {
        let bytes = self.markdown.as_bytes();
        if self.cursor >= bytes.len() {
            return None;
        }
        let start = self.cursor;
        while self.cursor < bytes.len() {
            match bytes[self.cursor] {
                b'\n' => {
                    let end = self.cursor;
                    self.cursor += 1;
                    return Some(&self.markdown[start..end]);
                }
                b'\r' => {
                    let end = self.cursor;
                    self.cursor += 1;
                    if self.cursor < bytes.len() && bytes[self.cursor] == b'\n' {
                        self.cursor += 1;
                    }
                    return Some(&self.markdown[start..end]);
                }
                _ => self.cursor += 1,
            }
        }
        Some(&self.markdown[start..])
    }
}

#[cfg(test)]
fn logical_lines(markdown: &str) -> Vec<&str> {
    LogicalLineIter::new(markdown).collect()
}

fn is_yaml_collection(field: &RawFrontmatterField) -> bool {
    if field.value.is_empty() {
        return !field.list_items.is_empty()
            && field.list_items.iter().all(|item| is_string_scalar(item));
    }
    if !(field.value.starts_with('[') && field.value.ends_with(']')) {
        return false;
    }
    let inner = field.value[1..field.value.len() - 1].trim();
    if inner.is_empty() {
        return true;
    }
    inner
        .split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .all(is_string_scalar)
}

fn is_legacy_tuple_collection(raw_value: &str) -> bool {
    let candidate = unquoted(raw_value);
    let candidate = candidate.trim();
    if !(candidate.starts_with('(') && candidate.ends_with(')')) {
        return false;
    }
    let inner = candidate[1..candidate.len() - 1].trim();
    if inner.is_empty() {
        return true;
    }
    let Some(items) = split_python_tuple_items(inner) else {
        return false;
    };
    items.iter().all(|item| is_python_string_literal(item))
}

fn split_python_tuple_items(inner: &str) -> Option<Vec<&str>> {
    let mut items = Vec::new();
    let mut quote: Option<char> = None;
    let mut escaped = false;
    let mut start = 0_usize;
    let mut saw_comma = false;
    for (index, character) in inner.char_indices() {
        if let Some(active_quote) = quote {
            if escaped {
                escaped = false;
                continue;
            }
            if character == '\\' {
                escaped = true;
                continue;
            }
            if character == active_quote {
                quote = None;
            }
            continue;
        }
        if matches!(character, '\'' | '"') {
            quote = Some(character);
            continue;
        }
        if character == ',' {
            saw_comma = true;
            items.push(inner[start..index].trim());
            start = index + character.len_utf8();
        }
    }
    if quote.is_some() || escaped || !saw_comma {
        return None;
    }
    let tail = inner[start..].trim();
    if !tail.is_empty() {
        items.push(tail);
    }
    if items.iter().any(|item| item.is_empty()) {
        return None;
    }
    Some(items)
}

fn is_python_string_literal(value: &str) -> bool {
    let value = value.trim();
    value.len() >= 2
        && matches!(value.as_bytes()[0], b'\'' | b'"')
        && value.as_bytes()[value.len() - 1] == value.as_bytes()[0]
}

fn boolean_warning_code(raw_value: &str) -> Option<RawIntegrityFindingCode> {
    let candidate = unquoted(raw_value);
    if !(candidate.eq_ignore_ascii_case("true") || candidate.eq_ignore_ascii_case("false")) {
        return Some(RawIntegrityFindingCode::InvalidBooleanValue);
    }
    if candidate.as_ref() != raw_value {
        return Some(RawIntegrityFindingCode::StringBoolean);
    }
    None
}

fn is_string_scalar(raw_value: &str) -> bool {
    if raw_value.is_empty() {
        return false;
    }
    let bytes = raw_value.as_bytes();
    if bytes.len() >= 2 && matches!(bytes[0], b'\'' | b'"') && bytes[bytes.len() - 1] == bytes[0] {
        return true;
    }
    if matches!(
        raw_value.to_ascii_lowercase().as_str(),
        "true" | "false" | "null" | "~"
    ) {
        return false;
    }
    if is_number_scalar(raw_value) {
        return false;
    }
    !raw_value.starts_with(['[', '{'])
}

fn is_number_scalar(value: &str) -> bool {
    let bytes = value.as_bytes();
    if bytes.is_empty() {
        return false;
    }
    let mut index = usize::from(matches!(bytes[0], b'+' | b'-'));
    if index == bytes.len() {
        return false;
    }
    if bytes[index] == b'0' {
        index += 1;
        if index < bytes.len() && bytes[index].is_ascii_digit() {
            return false;
        }
    } else if matches!(bytes[index], b'1'..=b'9') {
        index += 1;
        while index < bytes.len() && bytes[index].is_ascii_digit() {
            index += 1;
        }
    } else {
        return false;
    }
    if index == bytes.len() {
        return true;
    }
    if bytes[index] == b'.' {
        index += 1;
        let fraction_start = index;
        while index < bytes.len() && bytes[index].is_ascii_digit() {
            index += 1;
        }
        return index > fraction_start && index == bytes.len();
    }
    if matches!(bytes[index], b'e' | b'E') {
        index += 1;
        if index < bytes.len() && matches!(bytes[index], b'+' | b'-') {
            index += 1;
        }
        let exponent_start = index;
        while index < bytes.len() && bytes[index].is_ascii_digit() {
            index += 1;
        }
        return index > exponent_start && index == bytes.len();
    }
    false
}

fn unquoted(raw_value: &str) -> Cow<'_, str> {
    let bytes = raw_value.as_bytes();
    if bytes.len() < 2 || !matches!(bytes[0], b'\'' | b'"') || bytes[bytes.len() - 1] != bytes[0] {
        return Cow::Borrowed(raw_value);
    }
    let inner = &raw_value[1..raw_value.len() - 1];
    if bytes[0] == b'\'' && inner.contains("''") {
        return Cow::Owned(inner.replace("''", "'"));
    }
    Cow::Borrowed(inner)
}

#[cfg(test)]
mod tests {
    use super::{is_legacy_tuple_collection, is_number_scalar, logical_lines};

    #[test]
    fn logical_lines_match_python_splitlines_for_lf_crlf_and_cr() {
        assert_eq!(logical_lines("a\nb\n"), vec!["a", "b"]);
        assert_eq!(logical_lines("a\r\nb\r\n"), vec!["a", "b"]);
        assert_eq!(logical_lines("a\rb\r"), vec!["a", "b"]);
    }

    #[test]
    fn legacy_tuple_detection_requires_python_string_tuple_shape() {
        assert!(is_legacy_tuple_collection("()"));
        assert!(is_legacy_tuple_collection("('a',)"));
        assert!(is_legacy_tuple_collection("\"('a', 'b')\""));
        assert!(!is_legacy_tuple_collection("('a')"));
        assert!(!is_legacy_tuple_collection("('a', 2)"));
        assert!(!is_legacy_tuple_collection("(a, b)"));
    }
    #[test]
    fn number_scalar_detection_matches_frozen_python_regex_semantics() {
        for value in ["0", "-0", "+1", "42", "1.5", "-0.25", "1e3", "1E-3"] {
            assert!(is_number_scalar(value), "value={value}");
        }
        for value in ["", "+", "01", ".5", "1.", "1.0e3", "NaN", "inf", "1_000"] {
            assert!(!is_number_scalar(value), "value={value}");
        }
    }
}
