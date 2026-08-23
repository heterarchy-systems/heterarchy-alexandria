//! Deterministic Obsidian reference extraction and edge-candidate planning.

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt::{Display, Formatter};

use fancy_regex::Regex as FancyRegex;
use regex::Regex;
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::ComputeContractVersion;
use crate::document_analysis::{DocumentId, RelativeVaultPath};
use crate::text_compat::trim_python_whitespace;

/// Version of the reference-extraction schema and compatibility algorithm.
pub const REFERENCE_EXTRACTION_VERSION: u16 = 1;

const MAX_DOCUMENTS_PER_BATCH: usize = 4_096;
const MAX_DOCUMENT_BYTES: usize = 16 * 1024 * 1024;
const MAX_BATCH_BYTES: usize = 128 * 1024 * 1024;
const MAX_FRONTMATTER_EDGES_PER_DOCUMENT: usize = 100_000;
const MAX_REFERENCES_PER_DOCUMENT: usize = 1_000_000;

const HTML_COMMENT_PATTERN: &str = r"(?s)<!--.*?-->";
const OBSIDIAN_COMMENT_PATTERN: &str = r"(?s)%%.*?%%";
const INLINE_CODE_PATTERN: &str = r"(?s)(`+).*?\1";
const WIKILINK_PATTERN: &str = r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]";

/// One Python-policy-resolved frontmatter relation submitted for normalization and dedup.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FrontmatterEdgeInput {
    target_path: Option<String>,
    target_note_id: Option<String>,
    relation: String,
    source_field: String,
}

impl FrontmatterEdgeInput {
    /// Create one explicit policy-tagged frontmatter relation candidate.
    ///
    /// # Errors
    ///
    /// Returns an error when relation or source-field identity is blank.
    pub fn new(
        target_path: Option<String>,
        target_note_id: Option<String>,
        relation: String,
        source_field: String,
    ) -> Result<Self, ReferenceBatchError> {
        if trim_python_whitespace(&relation).is_empty() {
            return Err(ReferenceBatchError::new(
                "frontmatter relation must not be blank",
            ));
        }
        if trim_python_whitespace(&source_field).is_empty() {
            return Err(ReferenceBatchError::new(
                "frontmatter source field must not be blank",
            ));
        }
        Ok(Self {
            target_path,
            target_note_id,
            relation,
            source_field,
        })
    }
}

/// One already-read note submitted for coarse-grained reference extraction.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReferenceDocumentInput {
    note_id: DocumentId,
    relative_path: RelativeVaultPath,
    alexandria_root: String,
    body: String,
    frontmatter_edges: Vec<FrontmatterEdgeInput>,
}

impl ReferenceDocumentInput {
    /// Create one bounded reference-extraction input.
    ///
    /// # Errors
    ///
    /// Returns an error when the body or explicit candidate set exceeds bounds.
    pub fn new(
        note_id: DocumentId,
        relative_path: RelativeVaultPath,
        alexandria_root: String,
        body: String,
        frontmatter_edges: Vec<FrontmatterEdgeInput>,
    ) -> Result<Self, ReferenceBatchError> {
        if body.len() > MAX_DOCUMENT_BYTES {
            return Err(ReferenceBatchError::new(format!(
                "document {} exceeds the {MAX_DOCUMENT_BYTES} byte reference limit",
                note_id.as_str()
            )));
        }
        if frontmatter_edges.len() > MAX_FRONTMATTER_EDGES_PER_DOCUMENT {
            return Err(ReferenceBatchError::new(format!(
                "document {} exceeds the {MAX_FRONTMATTER_EDGES_PER_DOCUMENT} frontmatter edge limit",
                note_id.as_str()
            )));
        }
        Ok(Self {
            note_id,
            relative_path,
            alexandria_root,
            body,
            frontmatter_edges,
        })
    }
}

/// Coarse-grained batch submitted to the pure Rust extraction core.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReferenceBatch {
    documents: Vec<ReferenceDocumentInput>,
}

impl ReferenceBatch {
    /// Validate batch cardinality and aggregate body bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when deterministic safety bounds are exceeded.
    pub fn new(documents: Vec<ReferenceDocumentInput>) -> Result<Self, ReferenceBatchError> {
        if documents.len() > MAX_DOCUMENTS_PER_BATCH {
            return Err(ReferenceBatchError::new(format!(
                "reference batch exceeds the {MAX_DOCUMENTS_PER_BATCH} item limit"
            )));
        }
        let total_bytes = documents.iter().try_fold(0_usize, |total, document| {
            total
                .checked_add(document.body.len())
                .ok_or_else(|| ReferenceBatchError::new("reference batch byte count overflow"))
        })?;
        if total_bytes > MAX_BATCH_BYTES {
            return Err(ReferenceBatchError::new(format!(
                "reference batch exceeds the {MAX_BATCH_BYTES} byte limit"
            )));
        }
        Ok(Self { documents })
    }
}

/// Invalid input or an impossible extraction invariant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReferenceBatchError {
    message: String,
}

impl ReferenceBatchError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for ReferenceBatchError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for ReferenceBatchError {}

/// Rendered Obsidian reference syntax.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReferenceKind {
    /// `[[...]]` syntax.
    Wikilink,
    /// `![[...]]` syntax, which the current graph contract also treats as a wikilink edge.
    Embed,
}

/// Character and byte offsets into the original Markdown body.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct ReferenceSourceRange {
    /// Inclusive Python-character start.
    pub char_start: usize,
    /// Exclusive Python-character end.
    pub char_end: usize,
    /// Inclusive UTF-8 byte start.
    pub byte_start: usize,
    /// Exclusive UTF-8 byte end.
    pub byte_end: usize,
}

/// One syntactic reference candidate in source order.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ReferenceCandidate {
    /// Stable source-order sequence.
    pub reference_index: usize,
    /// Wikilink or embed syntax.
    pub kind: ReferenceKind,
    /// Visible syntax after current comment/code filtering.
    pub raw_syntax: String,
    /// Raw target capture before target normalization.
    pub target_text: String,
    /// Optional heading fragment.
    pub heading: Option<String>,
    /// Optional display alias.
    pub alias: Option<String>,
    /// Normalized target path when accepted by the current path contract.
    pub normalized_target_path: Option<String>,
    /// Range covering the source syntax in the original body.
    pub source_range: ReferenceSourceRange,
}

/// Candidate edge source type preserved from the current graph contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EdgeSourceKind {
    /// Explicit frontmatter relation input.
    Frontmatter,
    /// Rendered body wikilink or embed.
    Wikilink,
}

/// One deterministic edge candidate before target lookup or persistence.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct EdgeCandidate {
    /// Source note identity.
    pub source_note_id: String,
    /// Source note path.
    pub source_path: String,
    /// Optional already-known target note identity.
    pub target_note_id: Option<String>,
    /// Normalized target note path.
    pub target_path: String,
    /// Python-policy-selected relation name.
    pub relation: String,
    /// Frontmatter or body source.
    pub source_kind: EdgeSourceKind,
    /// Current compatibility confidence.
    pub confidence: f64,
    /// Canonical SHA-256 edge identifier.
    pub edge_id: String,
    /// Exact current material used by the canonical SHA-256 edge identifier.
    pub identity_material: String,
    /// Source reference sequence for body edges.
    pub reference_index: Option<usize>,
}

/// Stable warning category for syntactic references rejected as note targets.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ExtractionWarningCode {
    /// Target syntax is external, empty, absolute, traversing, or fragment-only.
    RejectedTarget,
}

/// Non-fatal extraction warning.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ExtractionWarning {
    /// Stable warning code.
    pub code: ExtractionWarningCode,
    /// Bounded diagnostic.
    pub message: String,
    /// Body source range when the warning came from rendered syntax.
    pub source_range: Option<ReferenceSourceRange>,
    /// Frontmatter source field when the warning came from explicit policy input.
    pub source_field: Option<String>,
}

/// One complete deterministic extraction result.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ReferenceDocumentResult {
    /// Caller-owned note identity.
    pub note_id: DocumentId,
    /// Caller-owned source path.
    pub relative_path: RelativeVaultPath,
    /// Syntactic references in encounter order.
    pub references: Vec<ReferenceCandidate>,
    /// Deduplicated edge candidates in current Python order.
    pub edges: Vec<EdgeCandidate>,
    /// Rejected-target diagnostics.
    pub warnings: Vec<ExtractionWarning>,
}

/// Coarse-grained extraction response.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ReferenceBatchResult {
    /// Python/Rust compute contract version.
    pub contract_version: u16,
    /// Reference-extraction schema and algorithm version.
    pub extraction_version: u16,
    /// Results in request order.
    pub results: Vec<ReferenceDocumentResult>,
}

/// Extract visible references and build normalized, deduplicated edge candidates.
///
/// # Errors
///
/// Returns an error only for invalid repository-owned regexes or internal source-map invariants.
pub fn extract_reference_batch(
    batch: ReferenceBatch,
) -> Result<ReferenceBatchResult, ReferenceBatchError> {
    let patterns = ExtractionPatterns::compile()?;
    let mut results = Vec::with_capacity(batch.documents.len());
    for document in batch.documents {
        results.push(extract_document(document, &patterns)?);
    }
    Ok(ReferenceBatchResult {
        contract_version: ComputeContractVersion::CURRENT.value(),
        extraction_version: REFERENCE_EXTRACTION_VERSION,
        results,
    })
}

struct ExtractionPatterns {
    html_comment: Regex,
    obsidian_comment: Regex,
    inline_code: FancyRegex,
    wikilink: Regex,
}

impl ExtractionPatterns {
    fn compile() -> Result<Self, ReferenceBatchError> {
        Ok(Self {
            html_comment: compile_regex("HTML comment", HTML_COMMENT_PATTERN)?,
            obsidian_comment: compile_regex("Obsidian comment", OBSIDIAN_COMMENT_PATTERN)?,
            inline_code: FancyRegex::new(INLINE_CODE_PATTERN).map_err(|error| {
                ReferenceBatchError::new(format!("invalid inline-code regex: {error}"))
            })?,
            wikilink: compile_regex("wikilink", WIKILINK_PATTERN)?,
        })
    }
}

fn compile_regex(name: &str, pattern: &str) -> Result<Regex, ReferenceBatchError> {
    Regex::new(pattern)
        .map_err(|error| ReferenceBatchError::new(format!("invalid {name} regex: {error}")))
}

fn extract_document(
    document: ReferenceDocumentInput,
    patterns: &ExtractionPatterns,
) -> Result<ReferenceDocumentResult, ReferenceBatchError> {
    let ReferenceDocumentInput {
        note_id,
        relative_path,
        alexandria_root,
        body,
        frontmatter_edges,
    } = document;
    let normalized_root = normalize_root(&alexandria_root);
    let source_note_id = note_id.as_str().to_owned();
    let source_path = relative_path.as_str().to_owned();
    let mut state = EdgePlanState::new(&source_note_id, &source_path, &normalized_root);
    state.append_frontmatter(frontmatter_edges);
    let references = state.extract_body(&body, patterns)?;
    Ok(ReferenceDocumentResult {
        note_id,
        relative_path,
        references,
        edges: state.edges,
        warnings: state.warnings,
    })
}

struct EdgePlanState<'source> {
    source_note_id: &'source str,
    source_path: &'source str,
    normalized_root: &'source str,
    seen: BTreeSet<(String, String, EdgeSourceKind, Option<String>)>,
    edges: Vec<EdgeCandidate>,
    warnings: Vec<ExtractionWarning>,
}

impl<'source> EdgePlanState<'source> {
    fn new(
        source_note_id: &'source str,
        source_path: &'source str,
        normalized_root: &'source str,
    ) -> Self {
        Self {
            source_note_id,
            source_path,
            normalized_root,
            seen: BTreeSet::new(),
            edges: Vec::new(),
            warnings: Vec::new(),
        }
    }

    fn append_frontmatter(&mut self, frontmatter_edges: Vec<FrontmatterEdgeInput>) {
        for frontmatter in frontmatter_edges {
            let Some(raw_target_path) = frontmatter.target_path.as_deref() else {
                continue;
            };
            let Some(target_path) = normalize_target_path(raw_target_path, self.normalized_root)
            else {
                self.warnings.push(ExtractionWarning {
                    code: ExtractionWarningCode::RejectedTarget,
                    message: "frontmatter target is not a valid internal note path".to_owned(),
                    source_range: None,
                    source_field: Some(frontmatter.source_field),
                });
                continue;
            };
            self.push_edge(EdgeCandidateInput {
                target_note_id: frontmatter.target_note_id,
                target_path,
                relation: frontmatter.relation,
                source_kind: EdgeSourceKind::Frontmatter,
                confidence: 1.0,
                reference_index: None,
            });
        }
    }

    fn extract_body(
        &mut self,
        body: &str,
        patterns: &ExtractionPatterns,
    ) -> Result<Vec<ReferenceCandidate>, ReferenceBatchError> {
        let linkable = linkable_markdown(body, patterns)?;
        let original_index = OriginalTextIndex::new(body);
        let mut references = Vec::new();
        for captures in patterns.wikilink.captures_iter(&linkable.text) {
            if references.len() >= MAX_REFERENCES_PER_DOCUMENT {
                return Err(ReferenceBatchError::new(format!(
                    "document {} exceeds the {MAX_REFERENCES_PER_DOCUMENT} reference limit",
                    self.source_note_id
                )));
            }
            let complete = captures
                .get(0)
                .ok_or_else(|| ReferenceBatchError::new("wikilink regex omitted complete match"))?;
            let target_capture = captures
                .get(1)
                .ok_or_else(|| ReferenceBatchError::new("wikilink regex omitted target capture"))?;
            let is_embed = complete.start() > 0
                && linkable.text.as_bytes().get(complete.start() - 1) == Some(&b'!');
            let visible_start = complete.start() - usize::from(is_embed);
            let source_range =
                linkable.source_range(visible_start, complete.end(), &original_index)?;
            let raw_wikilink = &linkable.text[complete.start()..complete.end()];
            let (heading, alias) = reference_fragments(raw_wikilink);
            let normalized_target_path =
                normalize_target_path(target_capture.as_str(), self.normalized_root);
            let reference_index = references.len();
            references.push(ReferenceCandidate {
                reference_index,
                kind: if is_embed {
                    ReferenceKind::Embed
                } else {
                    ReferenceKind::Wikilink
                },
                raw_syntax: linkable.text[visible_start..complete.end()].to_owned(),
                target_text: target_capture.as_str().to_owned(),
                heading,
                alias,
                normalized_target_path: normalized_target_path.clone(),
                source_range,
            });
            self.append_body_edge(normalized_target_path, source_range, reference_index);
        }
        Ok(references)
    }

    fn append_body_edge(
        &mut self,
        normalized_target_path: Option<String>,
        source_range: ReferenceSourceRange,
        reference_index: usize,
    ) {
        let Some(target_path) = normalized_target_path else {
            self.warnings.push(ExtractionWarning {
                code: ExtractionWarningCode::RejectedTarget,
                message: "wikilink target is not a valid internal note path".to_owned(),
                source_range: Some(source_range),
                source_field: None,
            });
            return;
        };
        if target_path == self.source_path {
            return;
        }
        self.push_edge(EdgeCandidateInput {
            target_note_id: None,
            target_path,
            relation: "wikilink".to_owned(),
            source_kind: EdgeSourceKind::Wikilink,
            confidence: 0.5,
            reference_index: Some(reference_index),
        });
    }

    fn push_edge(&mut self, input: EdgeCandidateInput) {
        let key = (
            input.target_path.clone(),
            input.relation.clone(),
            input.source_kind,
            input.target_note_id.clone(),
        );
        if self.seen.insert(key) {
            self.edges
                .push(edge_candidate(self.source_note_id, self.source_path, input));
        }
    }
}

struct EdgeCandidateInput {
    target_note_id: Option<String>,
    target_path: String,
    relation: String,
    source_kind: EdgeSourceKind,
    confidence: f64,
    reference_index: Option<usize>,
}

fn edge_candidate(
    source_note_id: &str,
    source_path: &str,
    input: EdgeCandidateInput,
) -> EdgeCandidate {
    let source_kind_text = match input.source_kind {
        EdgeSourceKind::Frontmatter => "frontmatter",
        EdgeSourceKind::Wikilink => "wikilink",
    };
    let identity_material = [
        source_note_id,
        source_path,
        input.target_note_id.as_deref().unwrap_or(""),
        &input.target_path,
        &input.relation,
        source_kind_text,
    ]
    .join("|");
    let edge_id = format!("{:x}", Sha256::digest(identity_material.as_bytes()));
    EdgeCandidate {
        source_note_id: source_note_id.to_owned(),
        source_path: source_path.to_owned(),
        target_note_id: input.target_note_id,
        target_path: input.target_path,
        relation: input.relation,
        source_kind: input.source_kind,
        confidence: input.confidence,
        edge_id,
        identity_material,
        reference_index: input.reference_index,
    }
}

fn normalize_root(root: &str) -> String {
    let normalized = trim_python_whitespace(root).trim_matches('/');
    if normalized.is_empty() {
        ".".to_owned()
    } else {
        normalized.to_owned()
    }
}

fn normalize_target_path(path: &str, root: &str) -> Option<String> {
    let mut normalized = trim_python_whitespace(path);
    if normalized.starts_with("[[") && normalized.ends_with("]]") {
        normalized = &normalized[2..normalized.len() - 2];
        normalized = normalized
            .split_once('|')
            .map_or(normalized, |parts| parts.0);
        normalized = normalized
            .split_once('#')
            .map_or(normalized, |parts| parts.0);
    }
    normalized = normalized.strip_prefix("./").unwrap_or(normalized);
    if normalized.is_empty()
        || normalized.contains("://")
        || normalized.starts_with('#')
        || normalized.to_ascii_lowercase().starts_with("artifact:")
        || normalized.to_ascii_lowercase().starts_with("evidence:")
    {
        return None;
    }
    let without_suffix = normalized.strip_suffix(".md").unwrap_or(normalized);
    let normalized_path = format!("{without_suffix}.md");
    if normalized_path.starts_with('/') || normalized_path.split('/').any(|segment| segment == "..")
    {
        return None;
    }
    if root == "." || normalized_path.starts_with(&format!("{root}/")) {
        Some(normalized_path)
    } else {
        Some(format!("{root}/{normalized_path}"))
    }
}

fn reference_fragments(raw_wikilink: &str) -> (Option<String>, Option<String>) {
    let inner = &raw_wikilink[2..raw_wikilink.len() - 2];
    let (target_and_heading, alias) = inner
        .split_once('|')
        .map_or((inner, None), |(target, alias)| {
            (target, Some(alias.to_owned()))
        });
    let heading = target_and_heading
        .split_once('#')
        .map(|(_, heading)| heading.to_owned());
    (heading, alias)
}

#[derive(Debug)]
struct OriginalTextIndex {
    byte_offsets: Vec<usize>,
}

impl OriginalTextIndex {
    fn new(text: &str) -> Self {
        let mut byte_offsets = text
            .char_indices()
            .map(|(offset, _)| offset)
            .collect::<Vec<_>>();
        byte_offsets.push(text.len());
        Self { byte_offsets }
    }

    fn byte_to_char(&self, byte_offset: usize) -> Result<usize, ReferenceBatchError> {
        self.byte_offsets.binary_search(&byte_offset).map_err(|_| {
            ReferenceBatchError::new(format!(
                "reference range is not on an original character boundary: {byte_offset}"
            ))
        })
    }
}

#[derive(Debug, Default)]
struct MappedText {
    text: String,
    origin_starts: Vec<usize>,
    origin_ends: Vec<usize>,
}

impl MappedText {
    fn append_original_range(&mut self, original: &str, start: usize, end: usize) {
        self.text.push_str(&original[start..end]);
        self.origin_starts.extend(start..end);
        self.origin_ends.extend((start + 1)..=end);
    }

    fn append_synthetic_newline(&mut self, original_newline_byte: usize) {
        self.text.push('\n');
        self.origin_starts.push(original_newline_byte);
        self.origin_ends.push(original_newline_byte + 1);
    }

    fn without_regular_matches(&self, pattern: &Regex) -> Self {
        let ranges = pattern
            .find_iter(&self.text)
            .map(|matched| (matched.start(), matched.end()))
            .collect::<Vec<_>>();
        self.without_ranges(&ranges)
    }

    fn without_fancy_matches(&self, pattern: &FancyRegex) -> Result<Self, ReferenceBatchError> {
        let mut ranges = Vec::new();
        for matched in pattern.find_iter(&self.text) {
            let matched = matched.map_err(|error| {
                ReferenceBatchError::new(format!("inline-code regex execution failed: {error}"))
            })?;
            ranges.push((matched.start(), matched.end()));
        }
        Ok(self.without_ranges(&ranges))
    }

    fn without_ranges(&self, ranges: &[(usize, usize)]) -> Self {
        let mut result = Self::default();
        let mut cursor = 0_usize;
        for (start, end) in ranges {
            result.append_mapped_range(self, cursor, *start);
            cursor = *end;
        }
        result.append_mapped_range(self, cursor, self.text.len());
        result
    }

    fn append_mapped_range(&mut self, source: &Self, start: usize, end: usize) {
        if start >= end {
            return;
        }
        self.text.push_str(&source.text[start..end]);
        self.origin_starts
            .extend_from_slice(&source.origin_starts[start..end]);
        self.origin_ends
            .extend_from_slice(&source.origin_ends[start..end]);
    }

    fn source_range(
        &self,
        visible_start: usize,
        visible_end: usize,
        original: &OriginalTextIndex,
    ) -> Result<ReferenceSourceRange, ReferenceBatchError> {
        if visible_start >= visible_end || visible_end > self.text.len() {
            return Err(ReferenceBatchError::new("invalid visible reference range"));
        }
        let byte_start = *self
            .origin_starts
            .get(visible_start)
            .ok_or_else(|| ReferenceBatchError::new("reference start is missing source mapping"))?;
        let byte_end = *self
            .origin_ends
            .get(visible_end - 1)
            .ok_or_else(|| ReferenceBatchError::new("reference end is missing source mapping"))?;
        Ok(ReferenceSourceRange {
            char_start: original.byte_to_char(byte_start)?,
            char_end: original.byte_to_char(byte_end)?,
            byte_start,
            byte_end,
        })
    }
}

fn linkable_markdown(
    body: &str,
    patterns: &ExtractionPatterns,
) -> Result<MappedText, ReferenceBatchError> {
    let mut visible = MappedText::default();
    let mut fence_character = None::<char>;
    let mut fence_length = 0_usize;
    for line in logical_lines(body) {
        let line_text = &body[line.start..line.end_with_ending];
        let stripped = line_text.trim_start_matches([' ', '\t']);
        if let Some(character) = fence_character {
            let closing = trim_python_whitespace(stripped.trim_end_matches(['\r', '\n']));
            if !closing.is_empty()
                && closing.chars().all(|candidate| candidate == character)
                && closing.chars().count() >= fence_length
            {
                fence_character = None;
                fence_length = 0;
            }
            append_hidden_line(&mut visible, body, line);
            continue;
        }
        if let Some((character, length)) = opening_fence(line_text) {
            fence_character = Some(character);
            fence_length = length;
            append_hidden_line(&mut visible, body, line);
            continue;
        }
        if line_text.starts_with("    ") || line_text.starts_with('\t') {
            append_hidden_line(&mut visible, body, line);
            continue;
        }
        visible.append_original_range(body, line.start, line.end_with_ending);
    }
    let visible = visible.without_regular_matches(&patterns.html_comment);
    let visible = visible.without_regular_matches(&patterns.obsidian_comment);
    visible.without_fancy_matches(&patterns.inline_code)
}

#[derive(Debug, Clone, Copy)]
struct LogicalLine {
    start: usize,
    end_with_ending: usize,
}

fn logical_lines(text: &str) -> Vec<LogicalLine> {
    let mut lines = Vec::new();
    let mut line_start = 0_usize;
    let mut characters = text.char_indices().peekable();
    while let Some((index, character)) = characters.next() {
        let ending_end = match character {
            '\r' => {
                if matches!(characters.peek(), Some((_, '\n'))) {
                    characters
                        .next()
                        .map_or(index + 1, |(next_index, next)| next_index + next.len_utf8())
                } else {
                    index + character.len_utf8()
                }
            }
            '\n' | '\u{000B}' | '\u{000C}' | '\u{001C}' | '\u{001D}' | '\u{001E}' | '\u{0085}'
            | '\u{2028}' | '\u{2029}' => index + character.len_utf8(),
            _ => continue,
        };
        lines.push(LogicalLine {
            start: line_start,
            end_with_ending: ending_end,
        });
        line_start = ending_end;
    }
    if line_start < text.len() {
        lines.push(LogicalLine {
            start: line_start,
            end_with_ending: text.len(),
        });
    }
    lines
}

fn opening_fence(line: &str) -> Option<(char, usize)> {
    let mut byte_index = 0_usize;
    let mut prefix_length = 0_usize;
    while prefix_length < 3 {
        let byte = line.as_bytes().get(byte_index).copied();
        if matches!(byte, Some(b' ' | b'\t')) {
            byte_index += 1;
            prefix_length += 1;
        } else {
            break;
        }
    }
    let marker = char::from(*line.as_bytes().get(byte_index)?);
    if !matches!(marker, '`' | '~') {
        return None;
    }
    let length = line[byte_index..]
        .chars()
        .take_while(|candidate| *candidate == marker)
        .count();
    (length >= 3).then_some((marker, length))
}

fn append_hidden_line(visible: &mut MappedText, body: &str, line: LogicalLine) {
    let line_text = &body[line.start..line.end_with_ending];
    if line_text.ends_with('\n') {
        visible.append_synthetic_newline(line.end_with_ending - 1);
    }
}

#[cfg(test)]
mod tests {
    use super::{
        EdgeSourceKind, FrontmatterEdgeInput, ReferenceBatch, ReferenceDocumentInput,
        ReferenceKind, extract_reference_batch,
    };
    use crate::document_analysis::{DocumentId, RelativeVaultPath};

    fn document(
        body: &str,
        frontmatter_edges: Vec<FrontmatterEdgeInput>,
    ) -> ReferenceDocumentInput {
        let note_id = match DocumentId::new("current".to_owned()) {
            Ok(value) => value,
            Err(error) => unreachable!("valid note id rejected: {error}"),
        };
        let relative_path =
            match RelativeVaultPath::new("Alexandria/Contexts/Current.md".to_owned()) {
                Ok(value) => value,
                Err(error) => unreachable!("valid source path rejected: {error}"),
            };
        match ReferenceDocumentInput::new(
            note_id,
            relative_path,
            "Alexandria".to_owned(),
            body.to_owned(),
            frontmatter_edges,
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid reference input rejected: {error}"),
        }
    }

    #[test]
    fn extracts_alias_heading_embed_and_source_ranges() {
        let body = "Read [[Prompts/Research#Scope|research]] and ![[Assets/Diagram]].";
        let batch = match ReferenceBatch::new(vec![document(body, Vec::new())]) {
            Ok(value) => value,
            Err(error) => unreachable!("valid batch rejected: {error}"),
        };
        let result = match extract_reference_batch(batch) {
            Ok(value) => value,
            Err(error) => unreachable!("reference extraction failed: {error}"),
        };
        let document = &result.results[0];
        assert_eq!(document.references.len(), 2);
        assert_eq!(document.references[0].heading.as_deref(), Some("Scope"));
        assert_eq!(document.references[0].alias.as_deref(), Some("research"));
        assert_eq!(document.references[1].kind, ReferenceKind::Embed);
        let range = document.references[1].source_range;
        assert_eq!(
            &body[range.byte_start..range.byte_end],
            "![[Assets/Diagram]]"
        );
        assert_eq!(document.edges.len(), 2);
    }

    #[test]
    fn ignores_comments_inline_code_fences_and_indented_code() {
        let body = concat!(
            "Visible [[Contexts/Source]].\n",
            "`inline [[Inline]]`\n",
            "<!-- [[HTML]] -->\n",
            "%% [[Obsidian]] %%\n",
            "```md\n[[Fenced]]\n```\n",
            "    [[Indented]]\n"
        );
        let batch = match ReferenceBatch::new(vec![document(body, Vec::new())]) {
            Ok(value) => value,
            Err(error) => unreachable!("valid batch rejected: {error}"),
        };
        let result = match extract_reference_batch(batch) {
            Ok(value) => value,
            Err(error) => unreachable!("reference extraction failed: {error}"),
        };
        assert_eq!(result.results[0].references.len(), 1);
        assert_eq!(
            result.results[0].edges[0].target_path,
            "Alexandria/Contexts/Source.md"
        );
    }

    #[test]
    fn frontmatter_order_precedes_deduplicated_body_edges() {
        let frontmatter = match FrontmatterEdgeInput::new(
            Some("START_HERE.md".to_owned()),
            Some("start".to_owned()),
            "cites".to_owned(),
            "source_refs".to_owned(),
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("valid frontmatter edge rejected: {error}"),
        };
        let body = "[[START_HERE]] [[START_HERE]] [[Alexandria/Contexts/Current]]";
        let batch = match ReferenceBatch::new(vec![document(body, vec![frontmatter])]) {
            Ok(value) => value,
            Err(error) => unreachable!("valid batch rejected: {error}"),
        };
        let result = match extract_reference_batch(batch) {
            Ok(value) => value,
            Err(error) => unreachable!("reference extraction failed: {error}"),
        };
        let edges = &result.results[0].edges;
        assert_eq!(edges.len(), 2);
        assert_eq!(edges[0].source_kind, EdgeSourceKind::Frontmatter);
        assert_eq!(edges[1].source_kind, EdgeSourceKind::Wikilink);
        assert_eq!(result.results[0].references.len(), 3);
    }
}
