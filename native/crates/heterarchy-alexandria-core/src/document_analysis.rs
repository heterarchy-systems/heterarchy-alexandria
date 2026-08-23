//! Deterministic Markdown document and frontmatter analysis.

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt::{Display, Formatter};

use serde::Serialize;

use crate::ComputeContractVersion;

/// Version of the document-analysis result schema.
pub const DOCUMENT_ANALYSIS_VERSION: u16 = 1;

const MAX_DOCUMENTS_PER_BATCH: usize = 4_096;
const MAX_DOCUMENT_BYTES: usize = 16 * 1024 * 1024;
const MAX_BATCH_BYTES: usize = 128 * 1024 * 1024;

/// Stable caller-owned identity for one document in a native batch.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(transparent)]
pub struct DocumentId(String);

impl DocumentId {
    /// Create a non-empty document identity.
    ///
    /// # Errors
    ///
    /// Returns an error when the identity is blank or contains a null byte.
    pub fn new(value: String) -> Result<Self, BatchValidationError> {
        validate_identity("document_id", &value)?;
        Ok(Self(value))
    }

    /// Return the caller-provided identity.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Caller-selected vault-relative path used only for result correlation.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(transparent)]
pub struct RelativeVaultPath(String);

impl RelativeVaultPath {
    /// Create a non-empty path identity without taking path-policy authority from Python.
    ///
    /// # Errors
    ///
    /// Returns an error when the path is blank or contains a null byte.
    pub fn new(value: String) -> Result<Self, BatchValidationError> {
        validate_identity("relative_path", &value)?;
        Ok(Self(value))
    }

    /// Return the caller-provided path identity.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

fn validate_identity(field_name: &str, value: &str) -> Result<(), BatchValidationError> {
    if value.trim().is_empty() {
        return Err(BatchValidationError::new(format!(
            "{field_name} must not be blank"
        )));
    }
    if value.contains('\0') {
        return Err(BatchValidationError::new(format!(
            "{field_name} must not contain a null byte"
        )));
    }
    Ok(())
}

/// One already-read Markdown document submitted for deterministic analysis.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DocumentInput {
    document_id: DocumentId,
    relative_path: RelativeVaultPath,
    text: String,
}

impl DocumentInput {
    /// Create one typed document input.
    ///
    /// # Errors
    ///
    /// Returns an error when the document exceeds the bounded native input size.
    pub fn new(
        document_id: DocumentId,
        relative_path: RelativeVaultPath,
        text: String,
    ) -> Result<Self, BatchValidationError> {
        if text.len() > MAX_DOCUMENT_BYTES {
            return Err(BatchValidationError::new(format!(
                "document {} exceeds the {} byte native analysis limit",
                document_id.as_str(),
                MAX_DOCUMENT_BYTES
            )));
        }
        Ok(Self {
            document_id,
            relative_path,
            text,
        })
    }
}

/// Coarse-grained batch passed from Python to the pure Rust compute core.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DocumentBatch {
    documents: Vec<DocumentInput>,
}

impl DocumentBatch {
    /// Validate batch cardinality and total input bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the batch exceeds the configured deterministic bounds.
    pub fn new(documents: Vec<DocumentInput>) -> Result<Self, BatchValidationError> {
        if documents.len() > MAX_DOCUMENTS_PER_BATCH {
            return Err(BatchValidationError::new(format!(
                "document batch exceeds the {MAX_DOCUMENTS_PER_BATCH} item limit"
            )));
        }
        let total_bytes = documents.iter().try_fold(0_usize, |total, document| {
            total
                .checked_add(document.text.len())
                .ok_or_else(|| BatchValidationError::new("document batch byte count overflow"))
        })?;
        if total_bytes > MAX_BATCH_BYTES {
            return Err(BatchValidationError::new(format!(
                "document batch exceeds the {MAX_BATCH_BYTES} byte limit"
            )));
        }
        Ok(Self { documents })
    }
}

/// Invalid coarse-grained input rejected before any document compute runs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BatchValidationError {
    message: String,
}

impl BatchValidationError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for BatchValidationError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for BatchValidationError {}

/// Byte offsets into the original UTF-8 document text.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct SourceRange {
    /// Inclusive byte start.
    pub start: usize,
    /// Exclusive byte end.
    pub end: usize,
}

impl SourceRange {
    const fn new(start: usize, end: usize) -> Self {
        Self { start, end }
    }
}

/// One deterministic top-level frontmatter entry in source order.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct FrontmatterEntry {
    /// Exact trimmed key spelling.
    pub key: String,
    /// Parsed scalar or flat scalar sequence.
    pub value: FrontmatterValue,
}

/// Frontmatter value types supported by the current Python-compatible parser.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum FrontmatterValue {
    /// Unquoted or quoted text.
    String(String),
    /// Canonical integer lexeme, preserved for arbitrary-precision Python conversion.
    Integer(String),
    /// Canonical float lexeme, preserved for Python-compatible conversion.
    Float(String),
    /// Boolean scalar.
    Boolean(bool),
    /// Explicit null scalar.
    Null,
    /// Flat YAML-style list supported by the current parser.
    Sequence(Vec<FrontmatterScalar>),
}

/// Scalar value allowed inside a frontmatter sequence.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum FrontmatterScalar {
    /// Text scalar.
    String(String),
    /// Canonical integer lexeme.
    Integer(String),
    /// Canonical float lexeme.
    Float(String),
    /// Boolean scalar.
    Boolean(bool),
    /// Explicit null scalar.
    Null,
}

impl From<FrontmatterScalar> for FrontmatterValue {
    fn from(value: FrontmatterScalar) -> Self {
        match value {
            FrontmatterScalar::String(text) => Self::String(text),
            FrontmatterScalar::Integer(integer) => Self::Integer(integer),
            FrontmatterScalar::Float(float) => Self::Float(float),
            FrontmatterScalar::Boolean(boolean) => Self::Boolean(boolean),
            FrontmatterScalar::Null => Self::Null,
        }
    }
}

/// One ATX heading observed outside a fenced code block.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HeadingEvent {
    /// Heading level from one through six.
    pub level: u8,
    /// Trimmed heading text after the marker.
    pub text: String,
    /// One-based line number in the original document.
    pub line_number: usize,
    /// Original line byte range without its line ending.
    pub source_range: SourceRange,
}

/// Successful deterministic analysis of one Markdown document.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DocumentAnalysis {
    /// Version of this analysis schema and structural algorithm.
    pub analysis_version: u16,
    /// Whether the first logical line opened a frontmatter block.
    pub has_frontmatter: bool,
    /// Parsed top-level frontmatter in source order.
    pub frontmatter: Vec<FrontmatterEntry>,
    /// Python-compatible body text returned by the current parser contract.
    pub body: String,
    /// Original frontmatter block range, including delimiters and closing line ending.
    pub frontmatter_source_range: Option<SourceRange>,
    /// Original frontmatter payload range, excluding delimiter lines.
    pub frontmatter_content_range: Option<SourceRange>,
    /// Original body range before line-ending normalization.
    pub body_source_range: SourceRange,
    /// Deterministically ordered structural heading events.
    pub headings: Vec<HeadingEvent>,
}

/// Stable machine-readable error category for one document analysis failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AnalysisErrorCode {
    /// Frontmatter could not be parsed under the canonical compatibility contract.
    FrontmatterParseError,
}

/// Structured failure returned for one item without aborting the rest of the batch.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AnalysisFailure {
    /// Stable error code.
    pub code: AnalysisErrorCode,
    /// Compatibility-preserving human-readable message.
    pub message: String,
    /// Whether callers may repair the source and retry.
    pub recoverable: bool,
}

/// One success or failure in the same order as the submitted documents.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum DocumentOutcome {
    /// Successful analysis.
    Success {
        /// Caller-provided document identity.
        document_id: DocumentId,
        /// Caller-provided path identity.
        relative_path: RelativeVaultPath,
        /// Complete deterministic analysis result.
        analysis: DocumentAnalysis,
    },
    /// Document-local parse failure.
    Error {
        /// Caller-provided document identity.
        document_id: DocumentId,
        /// Caller-provided path identity.
        relative_path: RelativeVaultPath,
        /// Structured failure details.
        error: AnalysisFailure,
    },
}

/// Coarse-grained result returned by one native batch call.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DocumentBatchResult {
    /// Python/Rust compute contract version.
    pub contract_version: u16,
    /// Document-analysis schema version.
    pub analysis_version: u16,
    /// Per-document outcomes in request order.
    pub results: Vec<DocumentOutcome>,
}

/// Analyze every document deterministically without performing I/O or persistence.
#[must_use]
pub fn analyze_batch(batch: DocumentBatch) -> DocumentBatchResult {
    let results = batch
        .documents
        .into_iter()
        .map(|document| {
            let DocumentInput {
                document_id,
                relative_path,
                text,
            } = document;
            match analyze_document(&text) {
                Ok(analysis) => DocumentOutcome::Success {
                    document_id,
                    relative_path,
                    analysis,
                },
                Err(error) => DocumentOutcome::Error {
                    document_id,
                    relative_path,
                    error: AnalysisFailure {
                        code: AnalysisErrorCode::FrontmatterParseError,
                        message: error.message,
                        recoverable: true,
                    },
                },
            }
        })
        .collect();
    DocumentBatchResult {
        contract_version: ComputeContractVersion::CURRENT.value(),
        analysis_version: DOCUMENT_ANALYSIS_VERSION,
        results,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ParseError {
    message: String,
}

impl ParseError {
    fn frontmatter(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

#[derive(Debug, Clone, Copy)]
struct LogicalLine<'text> {
    text: &'text str,
    start: usize,
    end: usize,
    ending_end: usize,
}

fn analyze_document(text: &str) -> Result<DocumentAnalysis, ParseError> {
    let lines = split_logical_lines(text);
    if lines.is_empty() || lines[0].text.trim() != "---" {
        return Ok(DocumentAnalysis {
            analysis_version: DOCUMENT_ANALYSIS_VERSION,
            has_frontmatter: false,
            frontmatter: Vec::new(),
            body: text.to_owned(),
            frontmatter_source_range: None,
            frontmatter_content_range: None,
            body_source_range: SourceRange::new(0, text.len()),
            headings: extract_headings(&lines, 0),
        });
    }

    let closing_index = lines
        .iter()
        .enumerate()
        .skip(1)
        .find_map(|(index, line)| (line.text.trim() == "---").then_some(index))
        .ok_or_else(|| {
            ParseError::frontmatter("FRONTMATTER_PARSE_ERROR: unterminated frontmatter")
        })?;
    let frontmatter = parse_frontmatter_lines(&lines[1..closing_index])?;
    let body_line_start = closing_index + 1;
    let body = normalized_body(text, &lines[body_line_start..]);
    let body_start = lines[closing_index].ending_end;
    let content_start = lines[0].ending_end;
    let content_end = lines[closing_index].start;

    Ok(DocumentAnalysis {
        analysis_version: DOCUMENT_ANALYSIS_VERSION,
        has_frontmatter: true,
        frontmatter,
        body,
        frontmatter_source_range: Some(SourceRange::new(0, body_start)),
        frontmatter_content_range: Some(SourceRange::new(content_start, content_end)),
        body_source_range: SourceRange::new(body_start, text.len()),
        headings: extract_headings(&lines[body_line_start..], body_line_start),
    })
}

fn normalized_body(text: &str, lines: &[LogicalLine<'_>]) -> String {
    let mut body = String::new();
    for (index, line) in lines.iter().enumerate() {
        if index > 0 {
            body.push('\n');
        }
        body.push_str(line.text);
    }
    if text.ends_with('\n') && !body.is_empty() {
        body.push('\n');
    }
    body
}

fn split_logical_lines(text: &str) -> Vec<LogicalLine<'_>> {
    let mut lines = Vec::new();
    let mut line_start = 0_usize;
    let mut characters = text.char_indices().peekable();
    while let Some((index, character)) = characters.next() {
        let ending_end = match character {
            '\r' => {
                if matches!(characters.peek(), Some((_, '\n'))) {
                    let next = characters.next();
                    next.map_or(
                        index + character.len_utf8(),
                        |(next_index, next_character)| next_index + next_character.len_utf8(),
                    )
                } else {
                    index + character.len_utf8()
                }
            }
            '\n' | '\u{000B}' | '\u{000C}' | '\u{001C}' | '\u{001D}' | '\u{001E}' | '\u{0085}'
            | '\u{2028}' | '\u{2029}' => index + character.len_utf8(),
            _ => continue,
        };
        lines.push(LogicalLine {
            text: &text[line_start..index],
            start: line_start,
            end: index,
            ending_end,
        });
        line_start = ending_end;
    }
    if line_start < text.len() {
        lines.push(LogicalLine {
            text: &text[line_start..],
            start: line_start,
            end: text.len(),
            ending_end: text.len(),
        });
    }
    lines
}

fn parse_frontmatter_lines(lines: &[LogicalLine<'_>]) -> Result<Vec<FrontmatterEntry>, ParseError> {
    let mut entries = Vec::<FrontmatterEntry>::new();
    let mut keys = BTreeSet::<String>::new();
    let mut active_list_index = None::<usize>;

    for line in lines {
        let stripped = line.text.trim();
        if stripped.is_empty() || stripped.starts_with('#') {
            continue;
        }
        if let Some(index) = active_list_index
            && let Some(raw_item) = stripped.strip_prefix('-')
        {
            let item = parse_scalar(raw_item.trim());
            if let Some(FrontmatterEntry {
                value: FrontmatterValue::Sequence(items),
                ..
            }) = entries.get_mut(index)
            {
                items.push(item);
            }
            continue;
        }
        if line.text != line.text.trim_start() {
            continue;
        }
        active_list_index = None;
        let Some((raw_key, raw_value)) = line.text.split_once(':') else {
            continue;
        };
        let key = raw_key.trim();
        if key.is_empty() {
            continue;
        }
        if !keys.insert(key.to_owned()) {
            return Err(ParseError::frontmatter(format!(
                "FRONTMATTER_PARSE_ERROR: duplicate top-level key: {key}"
            )));
        }
        let value_text = raw_value.trim();
        let value = if value_text.is_empty() {
            FrontmatterValue::Sequence(Vec::new())
        } else if value_text.starts_with('[') && value_text.ends_with(']') {
            FrontmatterValue::Sequence(parse_inline_list(value_text))
        } else {
            FrontmatterValue::from(parse_scalar(value_text))
        };
        entries.push(FrontmatterEntry {
            key: key.to_owned(),
            value,
        });
        if value_text.is_empty() {
            active_list_index = entries.len().checked_sub(1);
        }
    }
    Ok(entries)
}

fn parse_inline_list(value: &str) -> Vec<FrontmatterScalar> {
    let inner = &value[1..value.len() - 1];
    if inner.trim().is_empty() {
        return Vec::new();
    }
    let mut items = Vec::new();
    let mut quote = None::<char>;
    let mut escaped = false;
    let mut depth = 0_usize;
    let mut start = 0_usize;

    for (index, character) in inner.char_indices() {
        if let Some(active_quote) = quote {
            if character == active_quote && !escaped {
                quote = None;
            }
            escaped = character == '\\' && !escaped;
            continue;
        }
        if matches!(character, '\'' | '"') {
            quote = Some(character);
            escaped = false;
            continue;
        }
        match character {
            '[' | '{' | '(' => depth += 1,
            ']' | '}' | ')' => depth = depth.saturating_sub(1),
            ',' if depth == 0 => {
                items.push(parse_scalar(inner[start..index].trim()));
                start = index + character.len_utf8();
            }
            _ => {}
        }
    }
    items.push(parse_scalar(inner[start..].trim()));
    items
}

fn parse_scalar(raw: &str) -> FrontmatterScalar {
    let value = raw.trim();
    if value.len() >= 2 && value.starts_with('\'') && value.ends_with('\'') {
        return FrontmatterScalar::String(value[1..value.len() - 1].replace("''", "'"));
    }
    if value.len() >= 2 && value.starts_with('"') && value.ends_with('"') {
        return FrontmatterScalar::String(value[1..value.len() - 1].to_owned());
    }
    let lower = value.to_ascii_lowercase();
    if value.is_empty() || matches!(lower.as_str(), "null" | "~") {
        return FrontmatterScalar::Null;
    }
    if lower == "true" {
        return FrontmatterScalar::Boolean(true);
    }
    if lower == "false" {
        return FrontmatterScalar::Boolean(false);
    }
    if is_integer_lexeme(value) {
        return FrontmatterScalar::Integer(value.to_owned());
    }
    if is_float_lexeme(value) {
        return FrontmatterScalar::Float(value.to_owned());
    }
    FrontmatterScalar::String(value.to_owned())
}

fn is_integer_lexeme(value: &str) -> bool {
    canonical_unsigned_integer(strip_numeric_sign(value))
}

fn is_float_lexeme(value: &str) -> bool {
    let unsigned = strip_numeric_sign(value);
    if let Some((whole, fraction)) = unsigned.split_once('.') {
        return !fraction.is_empty()
            && !fraction.contains(['.', 'e', 'E'])
            && canonical_unsigned_integer(whole)
            && fraction.bytes().all(|byte| byte.is_ascii_digit());
    }

    let exponent_index = unsigned.find(['e', 'E']);
    let Some(index) = exponent_index else {
        return false;
    };
    let mantissa = &unsigned[..index];
    let exponent = &unsigned[index + 1..];
    if exponent.contains(['e', 'E']) {
        return false;
    }
    let exponent_digits = strip_numeric_sign(exponent);
    canonical_unsigned_integer(mantissa)
        && !exponent_digits.is_empty()
        && exponent_digits.bytes().all(|byte| byte.is_ascii_digit())
}

fn strip_numeric_sign(value: &str) -> &str {
    value
        .strip_prefix('+')
        .or_else(|| value.strip_prefix('-'))
        .unwrap_or(value)
}

fn canonical_unsigned_integer(value: &str) -> bool {
    if value == "0" {
        return true;
    }
    let mut bytes = value.bytes();
    let Some(first) = bytes.next() else {
        return false;
    };
    matches!(first, b'1'..=b'9') && bytes.all(|byte| byte.is_ascii_digit())
}

#[derive(Debug, Clone, Copy)]
struct Fence {
    marker: char,
    minimum_length: usize,
}

fn extract_headings(lines: &[LogicalLine<'_>], line_offset: usize) -> Vec<HeadingEvent> {
    let mut headings = Vec::new();
    let mut fence = None::<Fence>;
    for (relative_index, line) in lines.iter().enumerate() {
        if let Some(active_fence) = fence {
            if closes_fence(line.text, active_fence) {
                fence = None;
            }
            continue;
        }
        if let Some(opening_fence) = opening_fence(line.text) {
            fence = Some(opening_fence);
            continue;
        }
        if let Some((level, heading_text)) = parse_atx_heading(line.text) {
            headings.push(HeadingEvent {
                level,
                text: heading_text.to_owned(),
                line_number: line_offset + relative_index + 1,
                source_range: SourceRange::new(line.start, line.end),
            });
        }
    }
    headings
}

fn opening_fence(line: &str) -> Option<Fence> {
    let content = strip_up_to_three_spaces(line)?;
    let marker = content.chars().next()?;
    if !matches!(marker, '`' | '~') {
        return None;
    }
    let length = content
        .chars()
        .take_while(|character| *character == marker)
        .count();
    (length >= 3).then_some(Fence {
        marker,
        minimum_length: length,
    })
}

fn closes_fence(line: &str, fence: Fence) -> bool {
    let Some(content) = strip_up_to_three_spaces(line) else {
        return false;
    };
    let length = content
        .chars()
        .take_while(|character| *character == fence.marker)
        .count();
    if length < fence.minimum_length {
        return false;
    }
    content.chars().skip(length).all(char::is_whitespace)
}

fn strip_up_to_three_spaces(line: &str) -> Option<&str> {
    let leading_spaces = line.bytes().take_while(|byte| *byte == b' ').count();
    if leading_spaces > 3 {
        return None;
    }
    Some(&line[leading_spaces..])
}

fn parse_atx_heading(line: &str) -> Option<(u8, &str)> {
    let content = strip_up_to_three_spaces(line)?;
    let marker_count = content.bytes().take_while(|byte| *byte == b'#').count();
    if !(1..=6).contains(&marker_count) {
        return None;
    }
    let remainder = &content[marker_count..];
    if remainder.is_empty() {
        return u8::try_from(marker_count).ok().map(|level| (level, ""));
    }
    let first = remainder.chars().next()?;
    if !first.is_whitespace() {
        return None;
    }
    u8::try_from(marker_count)
        .ok()
        .map(|level| (level, remainder.trim()))
}

#[cfg(test)]
mod tests {
    use super::{
        AnalysisErrorCode, DocumentBatch, DocumentId, DocumentInput, DocumentOutcome,
        FrontmatterScalar, FrontmatterValue, RelativeVaultPath, analyze_batch,
    };

    fn input(document_id: &str, text: &str) -> DocumentInput {
        let document_id_result = DocumentId::new(document_id.to_owned());
        let path_result = RelativeVaultPath::new(format!("Contexts/{document_id}.md"));
        match (document_id_result, path_result) {
            (Ok(identifier), Ok(path)) => {
                let input_result = DocumentInput::new(identifier, path, text.to_owned());
                match input_result {
                    Ok(document) => document,
                    Err(error) => unreachable!("valid test input rejected: {error}"),
                }
            }
            (Err(error), _) | (_, Err(error)) => {
                unreachable!("valid test identity rejected: {error}")
            }
        }
    }

    fn one_outcome(text: &str) -> DocumentOutcome {
        let batch_result = DocumentBatch::new(vec![input("case", text)]);
        let batch = match batch_result {
            Ok(batch) => batch,
            Err(error) => unreachable!("valid test batch rejected: {error}"),
        };
        let result = analyze_batch(batch);
        let mut outcomes = result.results.into_iter();
        let outcome = outcomes.next();
        assert!(outcomes.next().is_none());
        match outcome {
            Some(value) => value,
            None => unreachable!("one input must produce one outcome"),
        }
    }

    #[test]
    fn no_frontmatter_preserves_original_body_bytes() {
        let text = "# Title\r\n\r\nBody\r\n";
        let outcome = one_outcome(text);
        match outcome {
            DocumentOutcome::Success { analysis, .. } => {
                assert!(!analysis.has_frontmatter);
                assert_eq!(analysis.body, text);
                assert_eq!(analysis.headings.len(), 1);
                assert_eq!(analysis.headings[0].text, "Title");
            }
            DocumentOutcome::Error { error, .. } => {
                unreachable!("unexpected parse failure: {}", error.message)
            }
        }
    }

    #[test]
    fn parses_python_compatible_frontmatter_types_and_normalizes_crlf_body() {
        let text = concat!(
            "---\r\n",
            "title: 'Alexandria''s Contract'\r\n",
            "enabled: TRUE\r\n",
            "priority: +3\r\n",
            "ratio: -0.5\r\n",
            "scientific: 2e+3\r\n",
            "quoted_numeric: \"3\"\r\n",
            "empty: null\r\n",
            "tags:\r\n",
            "  - alpha\r\n",
            "  - false\r\n",
            "source_refs: [{\"id\":\"ref-1\",\"detail_path\":\"Contexts/A.md\"}]\r\n",
            "---\r\n",
            "\r\n",
            "# Body\r\n"
        );
        let outcome = one_outcome(text);
        match outcome {
            DocumentOutcome::Success { analysis, .. } => {
                assert!(analysis.has_frontmatter);
                assert_eq!(analysis.body, "\n# Body\n");
                assert_eq!(analysis.frontmatter.len(), 9);
                assert_eq!(
                    analysis.frontmatter[0].value,
                    FrontmatterValue::String("Alexandria's Contract".to_owned())
                );
                assert_eq!(
                    analysis.frontmatter[1].value,
                    FrontmatterValue::Boolean(true)
                );
                assert_eq!(
                    analysis.frontmatter[2].value,
                    FrontmatterValue::Integer("+3".to_owned())
                );
                assert_eq!(
                    analysis.frontmatter[3].value,
                    FrontmatterValue::Float("-0.5".to_owned())
                );
                assert_eq!(
                    analysis.frontmatter[4].value,
                    FrontmatterValue::Float("2e+3".to_owned())
                );
                assert_eq!(
                    analysis.frontmatter[7].value,
                    FrontmatterValue::Sequence(vec![
                        FrontmatterScalar::String("alpha".to_owned()),
                        FrontmatterScalar::Boolean(false),
                    ])
                );
                assert_eq!(analysis.headings.len(), 1);
                assert_eq!(analysis.headings[0].line_number, 15);
            }
            DocumentOutcome::Error { error, .. } => {
                unreachable!("unexpected parse failure: {}", error.message)
            }
        }
    }

    #[test]
    fn duplicate_key_is_a_document_local_structured_failure() {
        let outcome = one_outcome("---\nid: one\nid: two\n---\n# Body\n");
        match outcome {
            DocumentOutcome::Error { error, .. } => {
                assert_eq!(error.code, AnalysisErrorCode::FrontmatterParseError);
                assert_eq!(
                    error.message,
                    "FRONTMATTER_PARSE_ERROR: duplicate top-level key: id"
                );
                assert!(error.recoverable);
            }
            DocumentOutcome::Success { .. } => unreachable!("duplicate key must fail"),
        }
    }

    #[test]
    fn unterminated_frontmatter_does_not_abort_other_batch_items() {
        let batch_result = DocumentBatch::new(vec![
            input("broken", "---\nid: broken\n"),
            input("valid", "# Valid\n"),
        ]);
        let batch = match batch_result {
            Ok(value) => value,
            Err(error) => unreachable!("valid test batch rejected: {error}"),
        };
        let result = analyze_batch(batch);
        assert_eq!(result.results.len(), 2);
        assert!(matches!(result.results[0], DocumentOutcome::Error { .. }));
        assert!(matches!(result.results[1], DocumentOutcome::Success { .. }));
    }

    #[test]
    fn headings_inside_fences_are_not_structural_events() {
        let outcome = one_outcome("# Visible\n```md\n## Hidden\n```\n  ### Nested\n");
        match outcome {
            DocumentOutcome::Success { analysis, .. } => {
                let headings = analysis
                    .headings
                    .iter()
                    .map(|heading| (heading.level, heading.text.as_str()))
                    .collect::<Vec<_>>();
                assert_eq!(headings, vec![(1, "Visible"), (3, "Nested")]);
            }
            DocumentOutcome::Error { error, .. } => {
                unreachable!("unexpected parse failure: {}", error.message)
            }
        }
    }
}
