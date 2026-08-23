//! Deterministic Python-compatible Markdown chunking.

use std::error::Error;
use std::fmt::{Display, Formatter};
use std::sync::OnceLock;

use regex::Regex;
use serde::Serialize;

use crate::ComputeContractVersion;
use crate::document_analysis::{DocumentId, RelativeVaultPath};
use crate::text_compat::{is_python_whitespace, trim_python_whitespace};

/// Version of the Markdown chunking schema and algorithm.
pub const MARKDOWN_CHUNKING_VERSION: u16 = 1;

const HEADING_PATTERN_TEXT: &str = r"(?m)^(#{1,6})\s+(.+)$";
const MAX_DOCUMENTS_PER_BATCH: usize = 4_096;
const MAX_DOCUMENT_BYTES: usize = 16 * 1024 * 1024;
const MAX_BATCH_BYTES: usize = 128 * 1024 * 1024;
const MAX_CHUNKS_PER_DOCUMENT: usize = 1_000_000;

static HEADING_PATTERN: OnceLock<Result<Regex, regex::Error>> = OnceLock::new();

/// Explicit caller-selected chunk-size policy.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct ChunkPolicy {
    /// Maximum Python-character count in one raw split window.
    pub max_chars: usize,
    /// Target overlap carried into the next raw split window.
    pub overlap_chars: usize,
}

impl ChunkPolicy {
    /// Validate a deterministic chunking policy.
    ///
    /// # Errors
    ///
    /// Returns an error when `max_chars` is zero or the overlap cannot be
    /// represented safely by the bounded native implementation.
    pub fn new(max_chars: usize, overlap_chars: usize) -> Result<Self, ChunkBatchError> {
        if max_chars == 0 {
            return Err(ChunkBatchError::new("max_chars must be greater than zero"));
        }
        if overlap_chars > MAX_DOCUMENT_BYTES {
            return Err(ChunkBatchError::new(format!(
                "overlap_chars exceeds the {MAX_DOCUMENT_BYTES} character safety bound"
            )));
        }
        Ok(Self {
            max_chars,
            overlap_chars,
        })
    }
}

/// One already-read title/body pair submitted for deterministic chunking.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChunkDocumentInput {
    document_id: DocumentId,
    relative_path: RelativeVaultPath,
    title: String,
    content: String,
}

impl ChunkDocumentInput {
    /// Create one typed Markdown chunking input.
    ///
    /// # Errors
    ///
    /// Returns an error when the combined title/body exceeds the native bound.
    pub fn new(
        document_id: DocumentId,
        relative_path: RelativeVaultPath,
        title: String,
        content: String,
    ) -> Result<Self, ChunkBatchError> {
        let combined_bytes = title
            .len()
            .checked_add(content.len())
            .ok_or_else(|| ChunkBatchError::new("chunk document byte count overflow"))?;
        if combined_bytes > MAX_DOCUMENT_BYTES {
            return Err(ChunkBatchError::new(format!(
                "document {} exceeds the {MAX_DOCUMENT_BYTES} byte chunking limit",
                document_id.as_str()
            )));
        }
        Ok(Self {
            document_id,
            relative_path,
            title,
            content,
        })
    }
}

/// Coarse-grained Markdown chunking request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChunkBatch {
    policy: ChunkPolicy,
    documents: Vec<ChunkDocumentInput>,
}

impl ChunkBatch {
    /// Validate batch cardinality and aggregate bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the request exceeds deterministic safety bounds.
    pub fn new(
        policy: ChunkPolicy,
        documents: Vec<ChunkDocumentInput>,
    ) -> Result<Self, ChunkBatchError> {
        if documents.len() > MAX_DOCUMENTS_PER_BATCH {
            return Err(ChunkBatchError::new(format!(
                "chunk batch exceeds the {MAX_DOCUMENTS_PER_BATCH} item limit"
            )));
        }
        let total_bytes = documents.iter().try_fold(0_usize, |total, document| {
            let document_bytes = document
                .title
                .len()
                .checked_add(document.content.len())
                .ok_or_else(|| ChunkBatchError::new("chunk batch byte count overflow"))?;
            total
                .checked_add(document_bytes)
                .ok_or_else(|| ChunkBatchError::new("chunk batch byte count overflow"))
        })?;
        if total_bytes > MAX_BATCH_BYTES {
            return Err(ChunkBatchError::new(format!(
                "chunk batch exceeds the {MAX_BATCH_BYTES} byte limit"
            )));
        }
        Ok(Self { policy, documents })
    }
}

/// Invalid batch-level input or an impossible native invariant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChunkBatchError {
    message: String,
}

impl ChunkBatchError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for ChunkBatchError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for ChunkBatchError {}

/// Source selected by the deterministic chunking input contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ChunkSourceKind {
    /// Non-empty `content.strip()` was chunked.
    Content,
    /// Empty content caused `title.strip()` to be chunked.
    TitleFallback,
}

/// Character and UTF-8 byte offsets into the selected original source string.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct ChunkSourceRange {
    /// Inclusive Python-character start.
    pub char_start: usize,
    /// Exclusive Python-character end.
    pub char_end: usize,
    /// Inclusive UTF-8 byte start.
    pub byte_start: usize,
    /// Exclusive UTF-8 byte end.
    pub byte_end: usize,
}

/// One ordered chunk preserving the current Python observable fields.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ChunkRecord {
    /// Stable sequence in the document result.
    pub chunk_index: usize,
    /// Current leaf heading exactly as the Python implementation returns it.
    pub heading: Option<String>,
    /// Deterministic heading hierarchy derived from observed ATX levels.
    pub heading_path: Vec<String>,
    /// Exact Python-compatible chunk content.
    pub content: String,
    /// Whether content or title fallback supplied the chunk text.
    pub source_kind: ChunkSourceKind,
    /// Exact range of the trimmed chunk in the selected original source.
    pub source_range: ChunkSourceRange,
}

/// Stable document-local chunking failure category.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ChunkingErrorCode {
    /// Output cardinality exceeded the bounded native contract.
    CapacityExceeded,
}

/// Structured failure for one document without aborting the rest of the batch.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ChunkingFailure {
    /// Stable machine-readable error code.
    pub code: ChunkingErrorCode,
    /// Human-readable bounded diagnostic.
    pub message: String,
    /// Whether a smaller input or different policy can be retried.
    pub recoverable: bool,
}

/// One success or failure in request order.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum ChunkDocumentOutcome {
    /// Successful deterministic chunking.
    Success {
        /// Caller-owned identity.
        document_id: DocumentId,
        /// Caller-owned path identity.
        relative_path: RelativeVaultPath,
        /// Ordered chunks.
        chunks: Vec<ChunkRecord>,
    },
    /// Document-local bounded-capacity failure.
    Error {
        /// Caller-owned identity.
        document_id: DocumentId,
        /// Caller-owned path identity.
        relative_path: RelativeVaultPath,
        /// Structured failure details.
        error: ChunkingFailure,
    },
}

/// Coarse-grained result returned by one native chunking call.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ChunkBatchResult {
    /// Python/Rust compute contract version.
    pub contract_version: u16,
    /// Chunking schema and algorithm version.
    pub chunking_version: u16,
    /// Policy actually applied.
    pub policy: ChunkPolicy,
    /// Results in request order.
    pub results: Vec<ChunkDocumentOutcome>,
}

/// Chunk every submitted document without I/O or persistence effects.
///
/// # Errors
///
/// Returns an error only when the repository-owned constant regex cannot be
/// compiled, which indicates a build-time invariant defect rather than user data.
pub fn chunk_batch(batch: ChunkBatch) -> Result<ChunkBatchResult, ChunkBatchError> {
    let heading_pattern = HEADING_PATTERN.get_or_init(|| Regex::new(HEADING_PATTERN_TEXT));
    let heading_pattern = heading_pattern.as_ref().map_err(|error| {
        ChunkBatchError::new(format!("invalid canonical heading regex: {error}"))
    })?;
    let policy = batch.policy;
    let results = batch
        .documents
        .into_iter()
        .map(|document| chunk_document(document, policy, heading_pattern))
        .collect();
    Ok(ChunkBatchResult {
        contract_version: ComputeContractVersion::CURRENT.value(),
        chunking_version: MARKDOWN_CHUNKING_VERSION,
        policy,
        results,
    })
}

fn chunk_document(
    document: ChunkDocumentInput,
    policy: ChunkPolicy,
    heading_pattern: &Regex,
) -> ChunkDocumentOutcome {
    let ChunkDocumentInput {
        document_id,
        relative_path,
        title,
        content,
    } = document;
    let source = SelectedSource::select(&title, &content);
    match split_selected_source(&source, &title, policy, heading_pattern) {
        Ok(chunks) => ChunkDocumentOutcome::Success {
            document_id,
            relative_path,
            chunks,
        },
        Err(error) => ChunkDocumentOutcome::Error {
            document_id,
            relative_path,
            error,
        },
    }
}

#[derive(Debug)]
struct IndexedText<'text> {
    text: &'text str,
    characters: Vec<char>,
    byte_offsets: Vec<usize>,
}

impl<'text> IndexedText<'text> {
    fn new(text: &'text str) -> Self {
        let mut characters = Vec::with_capacity(text.len());
        let mut byte_offsets = Vec::with_capacity(text.len().saturating_add(1));
        for (byte_offset, character) in text.char_indices() {
            byte_offsets.push(byte_offset);
            characters.push(character);
        }
        byte_offsets.push(text.len());
        Self {
            text,
            characters,
            byte_offsets,
        }
    }

    fn byte_offset(&self, char_offset: usize) -> usize {
        self.byte_offsets[char_offset]
    }

    fn byte_to_char(&self, byte_offset: usize) -> Result<usize, ChunkBatchError> {
        self.byte_offsets.binary_search(&byte_offset).map_err(|_| {
            ChunkBatchError::new(format!(
                "regex returned a non-character-boundary byte offset: {byte_offset}"
            ))
        })
    }

    fn slice(&self, char_start: usize, char_end: usize) -> &str {
        &self.text[self.byte_offset(char_start)..self.byte_offset(char_end)]
    }
}

#[derive(Debug)]
struct SelectedSource<'text> {
    source_kind: ChunkSourceKind,
    original: IndexedText<'text>,
    normalized_char_start: usize,
    normalized_char_end: usize,
}

impl<'text> SelectedSource<'text> {
    fn select(title: &'text str, content: &'text str) -> Self {
        let content_index = IndexedText::new(content);
        let content_bounds =
            trimmed_bounds(&content_index.characters, 0, content_index.characters.len());
        if content_bounds.0 < content_bounds.1 {
            return Self {
                source_kind: ChunkSourceKind::Content,
                original: content_index,
                normalized_char_start: content_bounds.0,
                normalized_char_end: content_bounds.1,
            };
        }
        let title_index = IndexedText::new(title);
        let title_bounds = trimmed_bounds(&title_index.characters, 0, title_index.characters.len());
        Self {
            source_kind: ChunkSourceKind::TitleFallback,
            original: title_index,
            normalized_char_start: title_bounds.0,
            normalized_char_end: title_bounds.1,
        }
    }

    fn normalized_text(&self) -> &str {
        self.original
            .slice(self.normalized_char_start, self.normalized_char_end)
    }
}

#[derive(Debug, Clone)]
struct HeadingMatch {
    start_char: usize,
    level: usize,
    heading: String,
}

#[derive(Debug, Clone)]
struct Section {
    heading: Option<String>,
    heading_path: Vec<String>,
    char_start: usize,
    char_end: usize,
}

fn split_selected_source(
    source: &SelectedSource<'_>,
    title: &str,
    policy: ChunkPolicy,
    heading_pattern: &Regex,
) -> Result<Vec<ChunkRecord>, ChunkingFailure> {
    let normalized_text = source.normalized_text();
    let normalized = IndexedText::new(normalized_text);
    let sections = sections_for_text(&normalized, title, heading_pattern).map_err(|error| {
        ChunkingFailure {
            code: ChunkingErrorCode::CapacityExceeded,
            message: error.to_string(),
            recoverable: false,
        }
    })?;
    let mut chunks = Vec::new();
    for section in sections {
        split_section(source, &normalized, &section, policy, &mut chunks)?;
    }
    Ok(chunks)
}

fn sections_for_text(
    normalized: &IndexedText<'_>,
    title: &str,
    heading_pattern: &Regex,
) -> Result<Vec<Section>, ChunkBatchError> {
    let mut matches = Vec::new();
    for captures in heading_pattern.captures_iter(normalized.text) {
        let complete = captures
            .get(0)
            .ok_or_else(|| ChunkBatchError::new("heading regex omitted the complete match"))?;
        let markers = captures
            .get(1)
            .ok_or_else(|| ChunkBatchError::new("heading regex omitted marker capture"))?;
        let heading = captures
            .get(2)
            .ok_or_else(|| ChunkBatchError::new("heading regex omitted text capture"))?;
        let start_char = normalized.byte_to_char(complete.start())?;
        matches.push(HeadingMatch {
            start_char,
            level: markers.as_str().chars().count(),
            heading: trim_python_whitespace(heading.as_str()).to_owned(),
        });
    }

    if matches.is_empty() {
        return Ok(vec![Section {
            heading: Some(title.to_owned()),
            heading_path: fallback_heading_path(title),
            char_start: 0,
            char_end: normalized.characters.len(),
        }]);
    }

    let mut sections = Vec::with_capacity(matches.len().saturating_add(1));
    if matches[0].start_char > 0 {
        let (char_start, char_end) =
            trimmed_bounds(&normalized.characters, 0, matches[0].start_char);
        sections.push(Section {
            heading: Some(title.to_owned()),
            heading_path: fallback_heading_path(title),
            char_start,
            char_end,
        });
    }

    let mut hierarchy = Vec::<String>::new();
    for (index, heading_match) in matches.iter().enumerate() {
        let target_parent_depth = heading_match.level.saturating_sub(1);
        hierarchy.truncate(target_parent_depth.min(hierarchy.len()));
        hierarchy.push(heading_match.heading.clone());
        let section_end = matches
            .get(index.saturating_add(1))
            .map_or(normalized.characters.len(), |next| next.start_char);
        let (char_start, char_end) = trimmed_bounds(
            &normalized.characters,
            heading_match.start_char,
            section_end,
        );
        sections.push(Section {
            heading: Some(heading_match.heading.clone()),
            heading_path: hierarchy.clone(),
            char_start,
            char_end,
        });
    }
    Ok(sections)
}

fn fallback_heading_path(title: &str) -> Vec<String> {
    if title.is_empty() {
        Vec::new()
    } else {
        vec![title.to_owned()]
    }
}

fn split_section(
    source: &SelectedSource<'_>,
    normalized: &IndexedText<'_>,
    section: &Section,
    policy: ChunkPolicy,
    chunks: &mut Vec<ChunkRecord>,
) -> Result<(), ChunkingFailure> {
    if section.char_start >= section.char_end {
        return Ok(());
    }
    let section_characters = &normalized.characters[section.char_start..section.char_end];
    let mut start = 0_usize;
    while start < section_characters.len() {
        let hard_end = start
            .checked_add(policy.max_chars)
            .map_or(section_characters.len(), |candidate| {
                candidate.min(section_characters.len())
            });
        let end = preferred_chunk_end(section_characters, start, hard_end);
        let (trimmed_start, trimmed_end) = trimmed_bounds(section_characters, start, end);
        if trimmed_start < trimmed_end {
            if chunks.len() >= MAX_CHUNKS_PER_DOCUMENT {
                return Err(ChunkingFailure {
                    code: ChunkingErrorCode::CapacityExceeded,
                    message: format!(
                        "document exceeds the {MAX_CHUNKS_PER_DOCUMENT} chunk output limit"
                    ),
                    recoverable: true,
                });
            }
            let normalized_char_start = section
                .char_start
                .checked_add(trimmed_start)
                .ok_or_else(chunk_range_failure)?;
            let normalized_char_end = section
                .char_start
                .checked_add(trimmed_end)
                .ok_or_else(chunk_range_failure)?;
            let source_char_start = source
                .normalized_char_start
                .checked_add(normalized_char_start)
                .ok_or_else(chunk_range_failure)?;
            let source_char_end = source
                .normalized_char_start
                .checked_add(normalized_char_end)
                .ok_or_else(chunk_range_failure)?;
            let source_byte_start = source.original.byte_offset(source_char_start);
            let source_byte_end = source.original.byte_offset(source_char_end);
            chunks.push(ChunkRecord {
                chunk_index: chunks.len(),
                heading: section.heading.clone(),
                heading_path: section.heading_path.clone(),
                content: normalized
                    .slice(normalized_char_start, normalized_char_end)
                    .to_owned(),
                source_kind: source.source_kind,
                source_range: ChunkSourceRange {
                    char_start: source_char_start,
                    char_end: source_char_end,
                    byte_start: source_byte_start,
                    byte_end: source_byte_end,
                },
            });
        }
        if end >= section_characters.len() {
            break;
        }
        let overlap_start = end.saturating_sub(policy.overlap_chars);
        let mut next_start = start.saturating_add(1).max(overlap_start);
        while next_start < end
            && next_start > start
            && !is_python_whitespace(section_characters[next_start - 1])
        {
            next_start = next_start.saturating_add(1);
        }
        start = next_start;
    }
    Ok(())
}

fn chunk_range_failure() -> ChunkingFailure {
    ChunkingFailure {
        code: ChunkingErrorCode::CapacityExceeded,
        message: "chunk source range overflow".to_owned(),
        recoverable: false,
    }
}

fn preferred_chunk_end(section: &[char], start: usize, hard_end: usize) -> usize {
    if hard_end >= section.len() {
        return section.len();
    }
    let minimum_end = start + ((hard_end - start) / 2);
    for (separator, adjustment) in [
        (&['\n', '\n'][..], 2_usize),
        (&['\n'][..], 1_usize),
        (&['.', ' '][..], 1_usize),
        (&[' '][..], 1_usize),
    ] {
        if let Some(boundary) = rfind_separator(section, separator, minimum_end, hard_end) {
            return boundary + adjustment;
        }
    }
    hard_end
}

fn rfind_separator(
    section: &[char],
    separator: &[char],
    minimum_start: usize,
    exclusive_end: usize,
) -> Option<usize> {
    if separator.is_empty() || exclusive_end < separator.len() {
        return None;
    }
    let latest_start = exclusive_end - separator.len();
    if latest_start < minimum_start {
        return None;
    }
    (minimum_start..=latest_start)
        .rev()
        .find(|start| section[*start..*start + separator.len()] == *separator)
}

fn trimmed_bounds(characters: &[char], start: usize, end: usize) -> (usize, usize) {
    let mut trimmed_start = start;
    while trimmed_start < end && is_python_whitespace(characters[trimmed_start]) {
        trimmed_start += 1;
    }
    let mut trimmed_end = end;
    while trimmed_end > trimmed_start && is_python_whitespace(characters[trimmed_end - 1]) {
        trimmed_end -= 1;
    }
    (trimmed_start, trimmed_end)
}

#[cfg(test)]
mod tests {
    use super::{
        ChunkBatch, ChunkDocumentInput, ChunkDocumentOutcome, ChunkPolicy, ChunkSourceKind,
        chunk_batch,
    };
    use crate::document_analysis::{DocumentId, RelativeVaultPath};

    fn input(title: &str, content: &str) -> ChunkDocumentInput {
        let document_id = match DocumentId::new("case".to_owned()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid identity rejected: {error}"),
        };
        let relative_path = match RelativeVaultPath::new("Contexts/Case.md".to_owned()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid path rejected: {error}"),
        };
        match ChunkDocumentInput::new(
            document_id,
            relative_path,
            title.to_owned(),
            content.to_owned(),
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid chunk input rejected: {error}"),
        }
    }

    fn chunks(
        title: &str,
        content: &str,
        max_chars: usize,
        overlap_chars: usize,
    ) -> Vec<super::ChunkRecord> {
        let policy = match ChunkPolicy::new(max_chars, overlap_chars) {
            Ok(value) => value,
            Err(error) => unreachable!("valid policy rejected: {error}"),
        };
        let batch = match ChunkBatch::new(policy, vec![input(title, content)]) {
            Ok(value) => value,
            Err(error) => unreachable!("valid batch rejected: {error}"),
        };
        let result = match chunk_batch(batch) {
            Ok(value) => value,
            Err(error) => unreachable!("chunking invariant failed: {error}"),
        };
        let mut outcomes = result.results.into_iter();
        let outcome = outcomes.next();
        assert!(outcomes.next().is_none());
        match outcome {
            Some(ChunkDocumentOutcome::Success { chunks, .. }) => chunks,
            Some(ChunkDocumentOutcome::Error { error, .. }) => {
                unreachable!("unexpected chunking failure: {}", error.message)
            }
            None => unreachable!("one input must produce one outcome"),
        }
    }

    #[test]
    fn preserves_current_leaf_heading_and_derives_hierarchy() {
        let result = chunks(
            "Decision log",
            "# Decision log\n\n## Summary\nUse local embeddings.\n\n### Evidence\nFastEmbed works locally.\n",
            1_400,
            160,
        );
        let headings = result
            .iter()
            .map(|chunk| chunk.heading.as_deref())
            .collect::<Vec<_>>();
        assert_eq!(
            headings,
            vec![Some("Decision log"), Some("Summary"), Some("Evidence")]
        );
        assert_eq!(
            result[2].heading_path,
            vec!["Decision log", "Summary", "Evidence"]
        );
    }

    #[test]
    fn uses_title_fallback_for_empty_content() {
        let result = chunks("  Fallback title  ", " \n\t", 1_400, 160);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].content, "Fallback title");
        assert_eq!(result[0].heading.as_deref(), Some("  Fallback title  "));
        assert_eq!(result[0].source_kind, ChunkSourceKind::TitleFallback);
        assert_eq!(result[0].source_range.char_start, 2);
        assert_eq!(result[0].source_range.char_end, 16);
    }

    #[test]
    fn bounds_a_single_unbroken_section_by_python_characters() {
        let content = "한".repeat(3_200);
        let result = chunks("Unicode", &content, 1_400, 160);
        let lengths = result
            .iter()
            .map(|chunk| chunk.content.chars().count())
            .collect::<Vec<_>>();
        assert_eq!(lengths, vec![1_400, 1_400, 400]);
        assert_eq!(result[0].source_range.byte_end, 4_200);
    }

    #[test]
    fn current_regex_semantics_treat_fenced_atx_lines_as_sections() {
        let result = chunks(
            "Fence",
            "```md\n# Inside fence\n```\n## Outside\nBody\n",
            1_400,
            160,
        );
        let headings = result
            .iter()
            .map(|chunk| chunk.heading.as_deref())
            .collect::<Vec<_>>();
        assert_eq!(
            headings,
            vec![Some("Fence"), Some("Inside fence"), Some("Outside")]
        );
    }
}
